"""CLI for Phase 2 paper organism."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from organism.config import ROOT, experiment_config, nim_config, resolve_path
from organism.evaluator import FitnessConfig, evaluate, run_episode
from organism.genome_loader import copy_genome, make_policy_factory
from organism.persistence import Store
from organism.sandbox import (
    SandboxConfig,
    build_sandbox_image,
    docker_available,
    evaluate_genome,
    image_exists,
    smoke_network_block,
)
from organism.weights import WeightConfig
from organism.world import WorldConfig

app = typer.Typer(add_completion=False, no_args_is_help=True, help="self-evolving-organism Phase 2 CLI")
console = Console()


def _load_cfgs():
    exp = experiment_config()
    world = WorldConfig.from_dict(exp.get("world", {}))
    fit = FitnessConfig.from_dict(exp.get("fitness", {}), exp.get("world", {}))
    wcfg = WeightConfig(
        alpha=float(exp.get("weights", {}).get("alpha", 0.05)),
        init_std=float(exp.get("weights", {}).get("init_std", 0.01)),
        clip_abs=float(exp.get("weights", {}).get("clip_abs", 5.0)),
        explore_train=float(exp.get("weights", {}).get("explore_train", 0.10)),
        explore_eval=float(exp.get("weights", {}).get("explore_eval", 0.05)),
    )
    return exp, world, fit, wcfg


@app.command()
def init() -> None:
    """Create artifacts dir, DB, and copy seed genome."""
    exp, _, _, _ = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    seed = resolve_path(exp.get("paths", {}).get("seed_genome", "genomes/seed"))
    dest = artifacts / "genomes" / "seed"
    artifacts.mkdir(parents=True, exist_ok=True)
    copy_genome(seed, dest)
    store = Store(db)
    gid = store.insert_genome(genome_id="g_seed", status="active", ablation="B0", artifact_path=str(dest))
    store.log_event("init", {"genome_id": gid, "artifact_path": str(dest)})
    store.close()
    console.print(f"[green]OK[/green] artifacts={artifacts}")
    console.print(f"[green]OK[/green] db={db} genome={gid}")


@app.command()
def demo(
    seed: int = typer.Option(0, help="Episode seed"),
    ablation: str = typer.Option("B0", help="B0|Bw|Bc|Bcw"),
) -> None:
    """Run a single episode and print summary."""
    exp, world, fit, wcfg = _load_cfgs()
    genome = resolve_path(exp.get("paths", {}).get("seed_genome", "genomes/seed"))
    factory = make_policy_factory(genome, ablation=ablation, weight_cfg=wcfg)
    train = ablation in ("Bw", "Bcw")
    policy = factory()
    summary = run_episode(policy, world, seed, train_weights=train)
    from organism.evaluator import episode_score

    summary.score = episode_score(summary, fit)
    console.print_json(data={
        "seed": summary.seed,
        "score": summary.score,
        "food": summary.food_collected,
        "ticks": summary.ticks_survived,
        "energy": summary.final_energy,
        "invalid": summary.invalid_actions,
        "walls": summary.wall_bumps,
        "death": summary.death_reason,
        "ablation": ablation,
    })


@app.command("eval")
def eval_cmd(
    ablation: str = typer.Option("B0", help="B0|Bw|Bc|Bcw"),
    holdout: bool = typer.Option(False, help="Use holdout seeds instead of train"),
    genome_id: str = typer.Option("g_seed", help="Genome id for DB logging"),
    weights: str = typer.Option("", help="Checkpoint path/id/latest/best for Bw/Bcw"),
    docker: bool = typer.Option(False, "--docker", help="Force Docker episode isolation"),
    host: bool = typer.Option(False, "--host", help="Force host-side evaluation"),
) -> None:
    """Multi-seed evaluation (frozen fitness)."""
    exp, world, fit, wcfg = _load_cfgs()
    eval_cfg = exp.get("eval", {})
    seeds = list(eval_cfg.get("holdout_seeds" if holdout else "train_seeds", list(range(8))))
    genome = resolve_path(exp.get("paths", {}).get("seed_genome", "genomes/seed"))
    # prefer active genome if present
    from organism.mutation import resolve_parent_genome

    try:
        active_path, active_id = resolve_parent_genome(exp)
        if (active_path / "policy.py").exists():
            genome = active_path
            if genome_id == "g_seed":
                genome_id = active_id
    except Exception:
        pass

    wpath = None
    if weights:
        from organism.checkpoints import resolve_checkpoint_path

        artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
        wpath = resolve_checkpoint_path(artifacts, weights)
        if ablation == "B0":
            ablation = "Bw"
    train = ablation in ("Bw", "Bcw") and not wpath
    sb = SandboxConfig.from_exp(exp)
    mode = "docker" if docker or (sb.episode_isolation and not host) else "host"
    console.print(
        f"[cyan]Evaluating[/cyan] ablation={ablation} seeds={seeds} "
        f"train_weights={train} weights={wpath or '—'} isolation={mode}"
    )
    result = evaluate_genome(
        genome,
        world=world,
        fit=fit,
        wcfg=wcfg,
        seeds=seeds,
        ablation=ablation,
        sandbox=sb,
        train_weights=train,
        weight_path=wpath,
        force_host=host,
        force_docker=docker,
    )

    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    store = Store(db)
    # ensure genome row
    try:
        store.insert_genome(
            genome_id=genome_id,
            status="active",
            ablation=ablation,
            artifact_path=str(genome),
        )
    except Exception:
        pass
    eid = store.insert_evaluation(
        genome_id,
        result.fitness,
        result.mean_score,
        result.std_score,
        result.seeds,
        result.episodes,
    )
    store.log_event(
        "evaluation",
        {
            "evaluation_id": eid,
            "genome_id": genome_id,
            "ablation": ablation,
            "fitness": result.fitness,
            "holdout": holdout,
        },
    )
    store.close()

    table = Table(title=f"Eval {ablation}")
    table.add_column("metric")
    table.add_column("value")
    table.add_row("fitness", f"{result.fitness:.4f}")
    table.add_row("mean_score", f"{result.mean_score:.4f}")
    table.add_row("std_score", f"{result.std_score:.4f}")
    table.add_row("n_episodes", str(len(result.episodes)))
    table.add_row("db_eval_id", eid)
    console.print(table)


@app.command()
def pins() -> None:
    """Show pinned free NIM models from config/.env."""
    cfg = nim_config()
    table = Table(title="NIM pins")
    table.add_column("role")
    table.add_column("model id")
    for k, v in (cfg.get("models") or {}).items():
        table.add_row(k, str(v))
    table.add_row("base_url", str(cfg.get("base_url")))
    table.add_row("api_key_set", "yes" if cfg.get("api_key") else "NO")
    table.add_row("max_rpm", str(cfg.get("max_rpm")))
    console.print(table)


@app.command("docker-build")
def docker_build(
    image: str = typer.Option("seo-sandbox:py312", help="Image tag"),
) -> None:
    """Build local sandbox image (python + numpy) for episode isolation."""
    if not docker_available():
        console.print("[red]Docker not available[/red]")
        raise typer.Exit(1)
    console.print(f"[cyan]Building[/cyan] {image} from Dockerfile.sandbox …")
    result = build_sandbox_image(image=image)
    if result["ok"]:
        console.print(f"[green]OK[/green] image={image}")
    else:
        console.print(result.get("stderr_tail", "")[-1500:])
        raise typer.Exit(1)


@app.command()
def docker_smoke() -> None:
    """Re-run Docker --network none smoke test."""
    if not docker_available():
        console.print("[red]Docker not available[/red]")
        raise typer.Exit(1)
    exp, _, _, _ = _load_cfgs()
    cfg = SandboxConfig.from_exp(exp)
    result = smoke_network_block(cfg)
    console.print_json(data=result)
    if not result["ok"]:
        raise typer.Exit(1)


@app.command("docker-eval")
def docker_eval(
    seeds: str = typer.Option("0,1", help="Comma-separated seeds"),
    ablation: str = typer.Option("Bc", help="B0|Bw|Bc|Bcw"),
) -> None:
    """Evaluate active/seed genome inside Docker (network-none)."""
    exp, world, fit, wcfg = _load_cfgs()
    from organism.mutation import resolve_parent_genome

    genome, gid = resolve_parent_genome(exp)
    seed_list = [int(s.strip()) for s in seeds.split(",") if s.strip()]
    sb = SandboxConfig.from_exp(exp)
    console.print(f"[cyan]Docker eval[/cyan] genome={genome} seeds={seed_list} image={sb.image}")
    result = evaluate_genome(
        genome,
        world=world,
        fit=fit,
        wcfg=wcfg,
        seeds=seed_list,
        ablation=ablation,
        sandbox=sb,
        train_weights=False,
        force_docker=True,
    )
    console.print_json(
        data={
            "genome_id": gid,
            "fitness": result.fitness,
            "mean_score": result.mean_score,
            "std_score": result.std_score,
            "seeds": result.seeds,
            "isolated": True,
        }
    )


@app.command()
def mutate_propose(
    ablation: str = typer.Option("Bc", help="Usually Bc or Bcw"),
) -> None:
    """Ask free NIM for a patch proposal only (no apply)."""
    from organism.mutation import propose_policy_patch, resolve_parent_genome

    exp, world, fit, wcfg = _load_cfgs()
    genome, _gid = resolve_parent_genome(exp)
    factory = make_policy_factory(genome, ablation="B0", weight_cfg=wcfg)
    summaries = []
    for s in [0, 1]:
        pol = factory()
        ep = run_episode(pol, world, s, train_weights=False)
        from organism.evaluator import episode_score

        ep.score = episode_score(ep, fit)
        summaries.append({
            "seed": ep.seed,
            "score": ep.score,
            "food": ep.food_collected,
            "ticks": ep.ticks_survived,
            "death": ep.death_reason,
        })
    console.print("[cyan]Requesting mutation proposal from NIM…[/cyan]")
    out = propose_policy_patch(genome, summaries)
    out_path = resolve_path("artifacts") / "last_mutation_proposal.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    console.print(f"[green]Wrote[/green] {out_path}")
    console.print(f"files parsed: {list((out.get('files') or {}).keys())}")
    console.print(out["proposal"][:1500] + ("…" if len(out["proposal"]) > 1500 else ""))


weights_app = typer.Typer(help="Weight checkpoint management")
app.add_typer(weights_app, name="weights")


@weights_app.command("train")
def weights_train(
    passes: int = typer.Option(2, help="Passes over train seeds"),
    genome_id: str = typer.Option("g_seed", help="Genome id label"),
    label: str = typer.Option("", help="Optional checkpoint label"),
    ablation: str = typer.Option("Bw", help="Bw or Bcw"),
) -> None:
    """Train phenotype weights and save checkpoint under artifacts/weights/."""
    from organism.checkpoints import train_and_checkpoint
    from organism.mutation import resolve_parent_genome

    exp, world, fit, wcfg = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    seeds = list(exp.get("eval", {}).get("train_seeds", list(range(8))))
    genome_dir, gid = resolve_parent_genome(exp)
    if genome_id != "g_seed":
        gid = genome_id

    console.print(f"[cyan]Training weights[/cyan] genome={genome_dir} passes={passes}")
    meta = train_and_checkpoint(
        genome_dir=genome_dir,
        world=world,
        wcfg=wcfg,
        train_seeds=seeds,
        artifacts_dir=artifacts,
        genome_id=gid,
        passes=passes,
        ablation=ablation if ablation in ("Bw", "Bcw") else "Bw",
        label=label or f"{gid}-p{passes}",
        fit_cfg=fit,
        eval_seeds=seeds,
    )
    store = Store(db)
    store.insert_weight_checkpoint(
        meta.checkpoint_id,
        meta.genome_id,
        meta.path,
        meta.sha256,
        meta.feature_dim,
        train_fitness=meta.train_fitness,
        holdout_fitness=meta.holdout_fitness,
        ablation=meta.ablation,
        episodes_trained=meta.episodes_trained,
        label=meta.label,
        meta=meta.to_dict(),
    )
    store.log_event("weight_checkpoint", meta.to_dict())
    store.close()

    table = Table(title=f"Checkpoint {meta.checkpoint_id}")
    table.add_column("field")
    table.add_column("value")
    table.add_row("path", meta.path)
    table.add_row("sha256", meta.sha256[:16] + "…")
    table.add_row("feature_dim", str(meta.feature_dim))
    table.add_row("episodes_trained", str(meta.episodes_trained))
    table.add_row(
        "train_fitness",
        "n/a" if meta.train_fitness is None else f"{meta.train_fitness:.4f}",
    )
    table.add_row("label", meta.label)
    console.print(table)


@weights_app.command("list")
def weights_list(
    limit: int = typer.Option(20, help="Max rows"),
) -> None:
    """List weight checkpoints (disk sidecars + DB)."""
    from organism.checkpoints import list_checkpoints

    exp, _, _, _ = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    metas = list_checkpoints(artifacts)[:limit]
    table = Table(title="Weight checkpoints")
    table.add_column("id")
    table.add_column("genome")
    table.add_column("train_fit")
    table.add_column("episodes")
    table.add_column("label")
    for m in metas:
        table.add_row(
            m.checkpoint_id,
            m.genome_id,
            "—" if m.train_fitness is None else f"{m.train_fitness:.3f}",
            str(m.episodes_trained),
            m.label[:24],
        )
    console.print(table)
    if not metas:
        console.print("[dim]No checkpoints yet — run: seo weights train[/dim]")
    try:
        store = Store(db)
        rows = store.list_weight_checkpoints(limit=limit)
        store.close()
        if rows:
            console.print(f"[dim]DB rows: {len(rows)}[/dim]")
    except Exception:
        pass


@weights_app.command("show")
def weights_show(
    ref: str = typer.Argument("latest", help="id | path | latest | best"),
) -> None:
    """Show checkpoint metadata and tensor shapes."""
    from organism.checkpoints import load_scorer, resolve_checkpoint_path

    exp, _, _, wcfg = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    path = resolve_checkpoint_path(artifacts, ref)
    scorer, meta = load_scorer(path, wcfg)
    console.print_json(
        data={
            "path": str(path),
            "theta_shape": list(scorer.theta.shape),
            "feature_dim": scorer.feature_dim,
            "baseline": scorer.baseline,
            "meta": None if meta is None else meta.to_dict(),
        }
    )


@app.command()
def evolve(
    cycles: int = typer.Option(5, help="Number of multi-seed eval cycles"),
    ablation: str = typer.Option("Bc", help="Bc or Bcw"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Offline mutations (no NIM)"),
    live: bool = typer.Option(False, "--live", help="Use free NIM for mutations"),
    max_mutations: int = typer.Option(None, help="Cap mutations this run"),
    every: int = typer.Option(None, help="Override schedule: mutate every N seed-episodes"),
    plateau: int = typer.Option(None, help="Override plateau window (seed-episodes)"),
) -> None:
    """Run continuous evolution with schedule + plateau mutation triggers."""
    from organism.evolve import EvolveConfig, run_evolve

    exp, world, fit, wcfg = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    use_dry = True if dry_run or not live else False
    cfg = EvolveConfig.from_exp(exp, dry_run=use_dry, ablation=ablation)
    if max_mutations is not None:
        cfg.max_mutations = max_mutations
    if every is not None:
        cfg.mutate_every_episodes = every
    if plateau is not None:
        cfg.plateau_episodes = plateau

    store = Store(db)
    console.print(
        f"[cyan]Evolve[/cyan] cycles={cycles} ablation={ablation} dry_run={cfg.dry_run} "
        f"every={cfg.mutate_every_episodes} plateau={cfg.plateau_episodes} max_mut={cfg.max_mutations}"
    )
    report = run_evolve(
        exp=exp,
        world=world,
        fit=fit,
        wcfg=wcfg,
        store=store,
        artifacts_dir=artifacts,
        max_eval_cycles=cycles,
        cfg=cfg,
    )
    store.close()

    table = Table(title=f"Evolve {report.run_id}")
    table.add_column("field")
    table.add_column("value")
    table.add_row("episodes_run", str(report.episodes_run))
    table.add_row(
        "mutations",
        f"acc={report.mutations_accepted} rej={report.mutations_rejected} "
        f"fail={report.mutations_failed} / att={report.mutations_attempted}",
    )
    table.add_row("start_genome", report.start_genome_id)
    table.add_row("final_genome", report.final_genome_id)
    if report.fitness_history:
        table.add_row("fitness_first", f"{report.fitness_history[0]:.4f}")
        table.add_row("fitness_last", f"{report.fitness_history[-1]:.4f}")
        table.add_row("fitness_best", f"{max(report.fitness_history):.4f}")
    table.add_row("triggers", ", ".join(
        e["kind"] for e in report.events if e["kind"].startswith("mutate_")
    ) or "—")
    console.print(table)
    console.print("[dim]Report: artifacts/last_evolve_report.json[/dim]")


@app.command()
def ablate(
    quick: bool = typer.Option(False, "--quick", help="Small seed sets + 1 dry-run mutation"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Force dry-run mutations (no NIM)"),
    live: bool = typer.Option(False, "--live", help="Force live NIM mutations"),
    max_mutations: int = typer.Option(None, help="Override max mutations for Bc/Bcw"),
    arms: str = typer.Option("B0,Bw,Bc,Bcw", help="Comma-separated arms"),
) -> None:
    """Run full B0/Bw/Bc/Bcw suite and report holdout δ (Bcw − B0)."""
    from organism.ablations import run_ablation_suite

    exp, world, fit, wcfg = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    seed = resolve_path(exp.get("paths", {}).get("seed_genome", "genomes/seed"))
    # ensure seed artifact exists
    seed_art = artifacts / "genomes" / "seed"
    seed_art.mkdir(parents=True, exist_ok=True)
    if not (seed_art / "policy.py").exists():
        copy_genome(seed, seed_art)

    dry: bool | None
    if live:
        dry = False
    elif dry_run or quick:
        dry = True
    else:
        dry = None  # suite defaults: quick→dry, full→live

    arm_list = [a.strip() for a in arms.split(",") if a.strip()]
    store = Store(db)
    console.print(
        f"[cyan]Ablation suite[/cyan] arms={arm_list} quick={quick} dry_run={dry} max_mutations={max_mutations}"
    )
    report = run_ablation_suite(
        exp=exp,
        world=world,
        fit=fit,
        wcfg=wcfg,
        store=store,
        artifacts_dir=artifacts,
        seed_dir=seed if (seed / "policy.py").exists() else seed_art,
        quick=quick,
        dry_run=dry,
        arms=arm_list,
        max_mutations=max_mutations,
    )
    store.close()

    table = Table(title=f"Ablation {report.run_id}")
    table.add_column("arm")
    table.add_column("train fit")
    table.add_column("holdout fit")
    table.add_column("mut acc/att")
    table.add_column("notes")
    for name in arm_list:
        if name not in report.arms:
            continue
        a = report.arms[name]
        table.add_row(
            name,
            f"{a.train_fitness:.4f}",
            f"{a.holdout_fitness:.4f}",
            f"{a.mutations_accepted}/{a.mutations_attempted}",
            a.notes[:40],
        )
    console.print(table)

    delta = report.delta_holdout_bcw_minus_b0
    thr = report.delta_success
    ok = report.success
    color = "green" if ok else "yellow"
    console.print(
        f"[{color}]holdout Bcw − B0 = {delta:.4f}[/{color}]  "
        f"(δ success threshold = {thr:.4f})  "
        f"success={ok}"
    )
    for k, v in report.comparisons.items():
        console.print(f"  {k}: {v:.4f}")
    console.print("[dim]Report: artifacts/last_ablation_report.json[/dim]")
    # Hypothesis fail is a scientific result, not a CLI error (exit 0).


@app.command()
def mutate(
    ablation: str = typer.Option("Bc", help="Bc (code only) or Bcw (code+weights)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Offline deterministic patch (no NIM)"),
    parent_id: str = typer.Option("", help="Override parent genome id"),
    critic: bool = typer.Option(
        True,
        "--critic/--no-critic",
        help="Run free-NIM critic (static + model) before candidate eval",
    ),
) -> None:
    """Run full mutation loop: propose → critic → apply → validate → eval → accept/reject."""
    from organism.mutation import resolve_parent_genome, run_mutation_cycle

    if ablation not in ("Bc", "Bcw", "B0", "Bw"):
        console.print("[red]ablation should be Bc or Bcw for mutation[/red]")
        raise typer.Exit(2)
    # code mutation ablations
    if ablation in ("B0", "Bw"):
        console.print("[yellow]Note:[/yellow] using heuristics path; prefer Bc/Bcw for genomic loop")

    exp, world, fit, wcfg = _load_cfgs()
    parent_dir, gid = resolve_parent_genome(exp)
    if parent_id:
        gid = parent_id
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    seeds = list(exp.get("eval", {}).get("train_seeds", list(range(8))))
    critic_cfg = dict(exp.get("critic") or {})
    # CLI flag wins over yaml
    use_critic = critic

    # ensure parent row exists
    store = Store(db)
    try:
        store.insert_genome(
            genome_id=gid,
            status="active",
            ablation=ablation,
            artifact_path=str(parent_dir),
        )
    except Exception:
        pass

    console.print(
        f"[cyan]Mutation cycle[/cyan] parent={gid} path={parent_dir} "
        f"ablation={ablation} dry_run={dry_run} critic={use_critic}"
    )
    result = run_mutation_cycle(
        parent_dir=parent_dir,
        artifacts_dir=artifacts,
        store=store,
        world=world,
        fit=fit,
        wcfg=wcfg,
        train_seeds=seeds,
        ablation=ablation if ablation in ("Bc", "Bcw") else "Bc",
        parent_genome_id=gid,
        dry_run=dry_run,
        critic=use_critic,
        critic_cfg=critic_cfg,
    )
    store.close()

    color = {"accepted": "green", "rejected": "yellow", "failed": "red"}.get(result.decision, "white")
    table = Table(title=f"Mutation {result.mutation_id}")
    table.add_column("field")
    table.add_column("value")
    table.add_row("decision", f"[{color}]{result.decision}[/{color}]")
    table.add_row("reason", result.reason)
    table.add_row("parent_fitness", f"{result.parent_fitness:.4f}")
    table.add_row(
        "candidate_fitness",
        "n/a" if result.candidate_fitness is None else f"{result.candidate_fitness:.4f}",
    )
    table.add_row("epsilon", f"{result.epsilon:.4f}")
    table.add_row("files", ", ".join(result.files_changed) or "—")
    table.add_row("model", result.model)
    table.add_row(
        "critic",
        (
            f"{result.critic_decision}"
            + (f" [{result.critic_code}]" if result.critic_code else "")
            + (
                f" conf={result.critic_confidence:.2f}"
                if result.critic_confidence is not None
                else ""
            )
        )
        or "—",
    )
    table.add_row("candidate_id", result.candidate_genome_id)
    table.add_row("candidate_path", result.candidate_path)
    table.add_row("rationale", (result.rationale or "")[:200])
    console.print(table)

    out_path = artifacts / "last_mutation_result.json"
    out_path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    console.print(f"[dim]Wrote {out_path}[/dim]")
    if result.decision == "failed":
        raise typer.Exit(1)


@app.callback()
def main() -> None:
    """self-evolving-organism CLI."""
    pass


if __name__ == "__main__":
    app()
