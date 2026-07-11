"""CLI for Phase 2 paper organism."""

from __future__ import annotations

import json
import shutil
import sys
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


def _configure_stdio_utf8() -> None:
    """Avoid UnicodeEncodeError on Windows cp1252 when jobs redirect logs."""
    for stream in (sys.stdout, sys.stderr):
        reconf = getattr(stream, "reconfigure", None)
        if callable(reconf):
            try:
                reconf(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _make_console() -> Console:
    # legacy_windows uses Win32 charmap (cp1252) and crashes on ε/δ/— in redirected jobs
    _configure_stdio_utf8()
    return Console(
        force_terminal=sys.stdout.isatty() if hasattr(sys.stdout, "isatty") else False,
        legacy_windows=False,
        soft_wrap=True,
    )


app = typer.Typer(add_completion=False, no_args_is_help=True, help="self-evolving-organism Phase 2 CLI")
console = _make_console()


def _load_cfgs():
    exp = experiment_config()
    world = WorldConfig.from_dict(exp.get("world", {}))
    fit = FitnessConfig.from_dict(exp.get("fitness", {}), exp.get("world", {}))
    w = exp.get("weights", {})
    wcfg = WeightConfig(
        alpha=float(w.get("alpha", 0.02)),
        init_std=float(w.get("init_std", 0.01)),
        clip_abs=float(w.get("clip_abs", 5.0)),
        explore_train=float(w.get("explore_train", 0.10)),
        explore_eval=float(w.get("explore_eval", 0.0)),
        gamma=float(w.get("gamma", 0.99)),
        bootstrap_episodes=int(w.get("bootstrap_episodes", 8)),
        bootstrap_alpha=float(w.get("bootstrap_alpha", 0.05)),
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
    # Bw without a checkpoint trains within a single episode and discards weights —
    # not a learning measurement (suite uses train→checkpoint→eval).
    if ablation == "Bw" and not wpath:
        console.print(
            "[red]seo eval --ablation Bw requires --weights[/red] "
            "(latest|best|path). Train first: seo weights train"
        )
        raise typer.Exit(2)
    if ablation == "Bcw" and not wpath:
        console.print(
            "[yellow]Note:[/yellow] Bcw without --weights trains within-episode only; "
            "prefer --weights after seo weights train for a real measurement."
        )
    train = ablation in ("Bw", "Bcw") and not wpath
    sb = SandboxConfig.from_exp(exp)
    mode = "docker" if docker or (sb.episode_isolation and not host) else "host"
    console.print(
        f"[cyan]Evaluating[/cyan] ablation={ablation} seeds={seeds} "
        f"train_weights={train} weights={wpath or '-'} isolation={mode}"
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
            "phenotype": result.phenotype,
            "fitness_code_only": result.fitness_code_only,
            "fitness_with_weights": result.fitness_with_weights,
        },
    )
    store.close()
    if result.phenotype:
        console.print(
            f"[dim]phenotype best={result.phenotype} "
            f"code_only={result.fitness_code_only} "
            f"with_weights={result.fitness_with_weights}[/dim]"
        )

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
    """Show pinned free NIM models + router role map + budgets."""
    from organism.router import FreeNimRouter

    cfg = nim_config()
    table = Table(title="NIM pins (config)")
    table.add_column("key")
    table.add_column("value")
    for k, v in (cfg.get("models") or {}).items():
        table.add_row(k, str(v))
    table.add_row("base_url", str(cfg.get("base_url")))
    table.add_row("api_key_set", "yes" if cfg.get("api_key") else "NO")
    table.add_row("max_rpm", str(cfg.get("max_rpm")))
    console.print(table)
    try:
        r = FreeNimRouter(cfg)
        rt = Table(title="Router roles -> free models")
        rt.add_column("role")
        rt.add_column("model")
        for role, model in r.pins().items():
            rt.add_row(role, model)
        console.print(rt)
        console.print(f"[dim]budget: {json.dumps(r.budget.to_dict())}[/dim]")
    except Exception as e:
        console.print(f"[dim]router unavailable: {e}[/dim]")


@app.command("docker-build")
def docker_build(
    image: str = typer.Option("seo-sandbox:py312", help="Image tag"),
) -> None:
    """Build local sandbox image (python + numpy) for episode isolation."""
    if not docker_available():
        console.print("[red]Docker not available[/red]")
        raise typer.Exit(1)
    console.print(f"[cyan]Building[/cyan] {image} from Dockerfile.sandbox ...")
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
    console.print("[cyan]Requesting mutation proposal from NIM...[/cyan]")
    out = propose_policy_patch(genome, summaries)
    out_path = resolve_path("artifacts") / "last_mutation_proposal.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    console.print(f"[green]Wrote[/green] {out_path}")
    console.print(f"files parsed: {list((out.get('files') or {}).keys())}")
    console.print(out["proposal"][:1500] + ("..." if len(out["proposal"]) > 1500 else ""))


weights_app = typer.Typer(help="Weight checkpoint management")
app.add_typer(weights_app, name="weights")

elite_app = typer.Typer(help="Phase 5 elite archive (promote / demote / list)")
app.add_typer(elite_app, name="elite")

runs_app = typer.Typer(help="Export machine reports to vault Runs/ lab notes")
app.add_typer(runs_app, name="runs")


@runs_app.command("export")
def runs_export_cmd(
    kind: str = typer.Option(
        "auto",
        help="auto | evolve | ablate | mutation (auto = newest last_* report)",
    ),
    title: str = typer.Option("", help="Optional note title"),
    slug: str = typer.Option("", help="Optional filename slug"),
    no_index: bool = typer.Option(False, "--no-index", help="Do not update Runs/README"),
    force: bool = typer.Option(False, "--force", help="Overwrite same slug if exists"),
) -> None:
    """Write a markdown run note under self-evolving-organism-docs/Runs/."""
    from organism.runs_export import export_run_note

    exp, _, _, _ = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    try:
        res = export_run_note(
            artifacts,
            kind=kind,
            title=title or None,
            slug=slug or None,
            update_index=not no_index,
            force=force,
        )
    except Exception as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2)
    console.print(f"[green]Wrote[/green] {res.path}")
    console.print(f"kind={res.kind} run_id={res.run_id}")


@elite_app.command("list")
def elite_list() -> None:
    """List genomes in the elite archive."""
    from organism.elites import list_elites

    exp, _, _, _ = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    elites = list_elites(artifacts)
    if not elites:
        console.print("[dim]No elites yet. Promote with: seo elite promote <genome_id>[/dim]")
        return
    table = Table(title="Elite archive")
    table.add_column("genome_id")
    table.add_column("fitness")
    table.add_column("path_ok")
    table.add_column("note")
    table.add_column("path")
    for e in elites:
        fit = e.get("fitness")
        table.add_row(
            str(e.get("genome_id")),
            "-" if fit is None else f"{float(fit):.4f}",
            "yes" if e.get("path_ok") else "NO",
            str(e.get("note") or "")[:40],
            str(e.get("path") or "")[:60],
        )
    console.print(table)
    console.print(f"[dim]Registry: {artifacts / 'elites' / 'registry.json'}[/dim]")


@elite_app.command("promote")
def elite_promote(
    genome_id: str = typer.Argument(..., help="Genome id to promote"),
    note: str = typer.Option("", help="Operator note"),
) -> None:
    """Add a genome to the elite archive (does not change active pointer)."""
    from organism.elites import promote_elite

    exp, _, _, _ = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    store = Store(db)
    try:
        entry = promote_elite(artifacts, store, genome_id, note=note)
    except Exception as e:
        store.close()
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(2)
    store.close()
    console.print(f"[green]Promoted elite[/green] {entry.get('genome_id')} path={entry.get('path')}")


@elite_app.command("demote")
def elite_demote(
    genome_id: str = typer.Argument(..., help="Genome id to remove from elites"),
) -> None:
    """Remove a genome from the elite archive."""
    from organism.elites import demote_elite

    exp, _, _, _ = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    store = Store(db)
    ok = demote_elite(artifacts, store, genome_id)
    store.close()
    if ok:
        console.print(f"[yellow]Demoted[/yellow] {genome_id}")
    else:
        console.print(f"[dim]Not in elite archive: {genome_id}[/dim]")
        raise typer.Exit(1)


@elite_app.command("select")
def elite_select(
    policy: str = typer.Option(
        "fitness_rank",
        "--policy",
        help="active | fitness_rank | tournament",
    ),
    tournament_k: int = typer.Option(3, help="Tournament k"),
    seed: int = typer.Option(0, help="RNG seed for tournament"),
) -> None:
    """Preview which parent selection would pick (does not mutate)."""
    from organism.selection import SELECT_POLICIES, select_and_resolve

    exp, _, _, _ = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    pol = (policy or "fitness_rank").strip().lower()
    if pol not in SELECT_POLICIES:
        console.print(f"[red]policy must be one of {SELECT_POLICIES}[/red]")
        raise typer.Exit(2)
    store = Store(db)
    res = select_and_resolve(
        artifacts,
        store,
        exp,
        policy=pol,
        tournament_k=int(tournament_k),
        seed=int(seed),
    )
    store.close()
    table = Table(title="Selection preview")
    table.add_column("field")
    table.add_column("value")
    for k, v in res.to_dict().items():
        if k == "shortlist":
            table.add_row(k, json.dumps(v)[:200])
        else:
            table.add_row(k, str(v))
    console.print(table)


@weights_app.command("train")
def weights_train(
    passes: int = typer.Option(2, help="Passes over train seeds"),
    genome_id: str = typer.Option("g_seed", help="Genome id label"),
    label: str = typer.Option("", help="Optional checkpoint label"),
    ablation: str = typer.Option("Bw", help="Bw or Bcw"),
    keep_if_beats_b0: bool = typer.Option(
        False,
        "--keep-if-beats-b0/--always-keep",
        help="Only update latest/best if holdout Bw beats B0",
    ),
) -> None:
    """Train phenotype weights and save checkpoint under artifacts/weights/."""
    from organism.checkpoints import train_and_checkpoint
    from organism.mutation import resolve_parent_genome

    exp, world, fit, wcfg = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    seeds = list(exp.get("eval", {}).get("train_seeds", list(range(8))))
    holdout = list(exp.get("eval", {}).get("holdout_seeds", list(range(8, 16))))
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
        holdout_seeds=holdout if keep_if_beats_b0 else None,
        keep_if_beats_b0=keep_if_beats_b0,
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
    table.add_row("sha256", meta.sha256[:16] + "...")
    table.add_row("feature_dim", str(meta.feature_dim))
    table.add_row("episodes_trained", str(meta.episodes_trained))
    table.add_row(
        "train_fitness",
        "n/a" if meta.train_fitness is None else f"{meta.train_fitness:.4f}",
    )
    table.add_row("label", meta.label)
    console.print(table)
    # surface discard diagnostics if present
    side = Path(meta.path).with_suffix(".json")
    if side.exists():
        try:
            side_d = json.loads(side.read_text(encoding="utf-8"))
            if side_d.get("discarded_for_eval"):
                console.print(
                    f"[yellow]Not promoted to latest/best:[/yellow] "
                    f"{side_d.get('discard_reason')}"
                )
            elif "holdout_delta_bw_minus_b0" in side_d:
                console.print(
                    f"[dim]holdout Bw-B0={side_d['holdout_delta_bw_minus_b0']:+.4f}[/dim]"
                )
        except Exception:
            pass


@weights_app.command("diagnose")
def weights_diagnose_cmd(
    weights: str = typer.Option("latest", help="Checkpoint id/path/latest/best"),
    margin: float = typer.Option(0.05, help="Min holdout gain to recommend USE weights"),
) -> None:
    """Diagnose whether a checkpoint beats B0 on train + holdout; write recommendation."""
    from organism.checkpoints import resolve_checkpoint_path
    from organism.mutation import resolve_parent_genome
    from organism.weights_diagnose import diagnose_weights

    exp, world, fit, wcfg = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    train_seeds = list(exp.get("eval", {}).get("train_seeds", list(range(8))))
    holdout = list(exp.get("eval", {}).get("holdout_seeds", list(range(8, 16))))
    genome_dir, gid = resolve_parent_genome(exp)
    wpath = resolve_checkpoint_path(artifacts, weights)
    report = diagnose_weights(
        genome_dir=genome_dir,
        genome_id=gid,
        world=world,
        fit=fit,
        wcfg=wcfg,
        train_seeds=train_seeds,
        holdout_seeds=holdout,
        weight_path=wpath,
        artifacts_dir=artifacts,
        margin=margin,
    )
    table = Table(title=f"Weights diagnose {report.run_id}")
    table.add_column("field")
    table.add_column("value")
    table.add_row("genome", report.genome_id)
    table.add_row("checkpoint", report.checkpoint_path)
    table.add_row("B0 train / Bw train", f"{report.b0_train:.4f} / {report.bw_train:.4f}")
    table.add_row(
        "B0 holdout / Bw holdout",
        f"{report.b0_holdout:.4f} / {report.bw_holdout:.4f}",
    )
    table.add_row("delta train", f"{report.delta_train:+.4f}")
    table.add_row("delta holdout", f"{report.delta_holdout:+.4f}")
    table.add_row("recommend_use_weights", str(report.recommend_use_weights))
    table.add_row("recommend_retrain", str(report.recommend_retrain))
    console.print(table)
    console.print(f"[cyan]{report.recommendation}[/cyan]")
    console.print("[dim]Report: artifacts/last_weights_diagnose.json[/dim]")


@weights_app.command("holdout")
def weights_holdout_cmd(
    weights: str = typer.Option(
        "latest",
        help="Checkpoint id/path/latest/best (required for real Bw measurement)",
    ),
    passes: int = typer.Option(
        0,
        help="If >0, train this many passes before holdout eval",
    ),
    host: bool = typer.Option(True, "--host/--docker", help="Eval isolation"),
) -> None:
    """
    Compare holdout fitness: B0 (no weights) vs Bw (frozen checkpoint).

    Use after `seo weights train`. Writes artifacts/last_weights_holdout.json.
    """
    from organism.checkpoints import resolve_checkpoint_path, train_and_checkpoint
    from organism.mutation import resolve_parent_genome
    from organism.weights_holdout import run_weights_holdout

    exp, world, fit, wcfg = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    holdout = list(exp.get("eval", {}).get("holdout_seeds", list(range(8, 16))))
    train_seeds = list(exp.get("eval", {}).get("train_seeds", list(range(8))))
    genome_dir, gid = resolve_parent_genome(exp)

    train_passes = int(passes)
    if train_passes > 0:
        console.print(
            f"[cyan]Training[/cyan] genome={genome_dir} passes={train_passes} then holdout"
        )
        meta = train_and_checkpoint(
            genome_dir=genome_dir,
            world=world,
            wcfg=wcfg,
            train_seeds=train_seeds,
            artifacts_dir=artifacts,
            genome_id=gid,
            passes=train_passes,
            ablation="Bw",
            label=f"{gid}-holdout-p{train_passes}",
            fit_cfg=fit,
            eval_seeds=train_seeds,
        )
        wpath = Path(meta.path)
        cid = meta.checkpoint_id
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
        store.close()
    else:
        wpath = resolve_checkpoint_path(artifacts, weights)
        cid = wpath.stem

    console.print(
        f"[cyan]Holdout compare[/cyan] genome={gid} B0 vs Bw weights={wpath} "
        f"seeds={holdout} host={host}"
    )
    from organism.sandbox import SandboxConfig

    sb = SandboxConfig.from_exp(exp)
    if host:
        sb.mode = "host"
        sb.episode_isolation = False
        sb.require_docker = False

    report = run_weights_holdout(
        genome_dir=genome_dir,
        genome_id=gid,
        world=world,
        fit=fit,
        wcfg=wcfg,
        holdout_seeds=holdout,
        artifacts_dir=artifacts,
        weight_path=wpath,
        checkpoint_id=cid,
        sandbox=sb,
        force_host=host,
        train_passes=train_passes,
    )
    store = Store(db)
    store.log_event("weights_holdout", report.to_dict())
    store.close()

    table = Table(title=f"Weights holdout {report.run_id}")
    table.add_column("field")
    table.add_column("value")
    table.add_row("genome", report.genome_id)
    table.add_row("checkpoint", report.checkpoint_id)
    table.add_row("B0 holdout", f"{report.b0.fitness:.4f}")
    table.add_row("Bw holdout", f"{report.bw.fitness:.4f}")
    color = "green" if report.bw_beats_b0 else "yellow"
    table.add_row(
        "Bw - B0",
        f"[{color}]{report.delta_bw_minus_b0:+.4f}[/{color}]  beats_b0={report.bw_beats_b0}",
    )
    best_ph = "with_weights" if report.bw_beats_b0 else "code_only"
    best_fit = max(report.b0.fitness, report.bw.fitness)
    table.add_row("phenotype_best", f"{best_ph} @ {best_fit:.4f}")
    console.print(table)
    console.print("[dim]Report: artifacts/last_weights_holdout.json[/dim]")


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
            "-" if m.train_fitness is None else f"{m.train_fitness:.3f}",
            str(m.episodes_trained),
            m.label[:24],
        )
    console.print(table)
    if not metas:
        console.print("[dim]No checkpoints yet - run: seo weights train[/dim]")
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
    select: str = typer.Option(
        "active",
        help="Parent selection: active | fitness_rank | tournament",
    ),
    tournament_k: int = typer.Option(3, help="Tournament shortlist size"),
    auto_elite: Optional[bool] = typer.Option(
        None,
        "--auto-elite/--no-auto-elite",
        help="Promote accepted children to elites (default: on when select!=active)",
    ),
    lineages: int = typer.Option(
        1,
        "--lineages",
        help="Concurrent lineage slots (1=classic single lineage; >1 multi-lineage)",
    ),
    mut_per_lineage: int = typer.Option(
        0,
        "--mut-per-lineage",
        help="Max mutations per lineage (0=unlimited except global)",
    ),
    cycles_per_lineage: int = typer.Option(
        0,
        "--cycles-per-lineage",
        help="Max eval cycles per lineage (0=unlimited except global)",
    ),
    lineage_schedule: str = typer.Option(
        "round_robin",
        help="Lineage pick schedule: round_robin | fitness_rank",
    ),
) -> None:
    """Run continuous evolution with schedule + plateau mutation triggers."""
    from organism.evolve import EvolveConfig, run_evolve
    from organism.selection import SELECT_POLICIES

    exp, world, fit, wcfg = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    from organism.observer.control import mutations_allowed

    ok, why = mutations_allowed(artifacts)
    if not ok:
        console.print(f"[red]Blocked by operator control:[/red] {why}")
        console.print("[dim]Clear via seo ui -> Control, or delete artifacts/control.json[/dim]")
        raise typer.Exit(3)
    use_dry = True if dry_run or not live else False
    cfg = EvolveConfig.from_exp(exp, dry_run=use_dry, ablation=ablation)
    if max_mutations is not None:
        cfg.max_mutations = max_mutations
    if every is not None:
        cfg.mutate_every_episodes = every
    if plateau is not None:
        cfg.plateau_episodes = plateau
    sel = (select or "active").strip().lower()
    if sel not in SELECT_POLICIES:
        console.print(f"[red]select must be one of {SELECT_POLICIES}[/red]")
        raise typer.Exit(2)
    cfg.select = sel
    cfg.tournament_k = int(tournament_k)
    if auto_elite is None:
        cfg.auto_elite_on_accept = sel != "active"
    else:
        cfg.auto_elite_on_accept = bool(auto_elite)
    cfg.max_lineages = max(1, int(lineages))
    cfg.max_mutations_per_lineage = max(0, int(mut_per_lineage))
    cfg.max_eval_cycles_per_lineage = max(0, int(cycles_per_lineage))
    ls = (lineage_schedule or "round_robin").strip().lower()
    if ls not in ("round_robin", "fitness_rank"):
        console.print("[red]lineage-schedule must be round_robin or fitness_rank[/red]")
        raise typer.Exit(2)
    cfg.lineage_schedule = ls

    store = Store(db)
    console.print(
        f"[cyan]Evolve[/cyan] cycles={cycles} ablation={ablation} dry_run={cfg.dry_run} "
        f"every={cfg.mutate_every_episodes} plateau={cfg.plateau_episodes} "
        f"max_mut={cfg.max_mutations} select={cfg.select} k={cfg.tournament_k} "
        f"lineages={cfg.max_lineages} schedule={cfg.lineage_schedule}"
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
    table.add_row("lineages", str(report.max_lineages))
    table.add_row("lineage_schedule", report.lineage_schedule)
    table.add_row("start_genome", report.start_genome_id)
    table.add_row("final_genome", report.final_genome_id)
    if report.fitness_history:
        table.add_row("fitness_first", f"{report.fitness_history[0]:.4f}")
        table.add_row("fitness_last", f"{report.fitness_history[-1]:.4f}")
        table.add_row("fitness_best", f"{max(report.fitness_history):.4f}")
    table.add_row("triggers", ", ".join(
        e["kind"] for e in report.events if e["kind"].startswith("mutate_")
    ) or "-")
    if report.lineages:
        for lin in report.lineages[:8]:
            table.add_row(
                f"slot_{lin.get('slot_id')}",
                f"{lin.get('genome_id')} fit={lin.get('fitness')} "
                f"eval={lin.get('eval_cycles')} mut={lin.get('mutations_attempted')} "
                f"exh={lin.get('exhausted')}",
            )
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
        f"[{color}]holdout Bcw - B0 = {delta:.4f}[/{color}]  "
        f"(delta success threshold = {thr:.4f})  "
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
    select: str = typer.Option(
        "active",
        help="If no --parent-id: active | fitness_rank | tournament",
    ),
    tournament_k: int = typer.Option(3, help="Tournament shortlist size"),
    critic: bool = typer.Option(
        True,
        "--critic/--no-critic",
        help="Run free-NIM critic (static + model) before candidate eval",
    ),
    force_bcw: bool = typer.Option(
        False,
        "--force-bcw",
        help="Allow Bcw even when weights diagnose says do not use weights",
    ),
) -> None:
    """Run full mutation loop: propose → critic → apply → validate → eval → accept/reject."""
    from organism.mutation import run_mutation_cycle
    from organism.safety import recommend_mutation_ablation
    from organism.selection import SELECT_POLICIES, select_and_resolve

    if ablation not in ("Bc", "Bcw", "B0", "Bw"):
        console.print("[red]ablation should be Bc or Bcw for mutation[/red]")
        raise typer.Exit(2)
    # code mutation ablations
    if ablation in ("B0", "Bw"):
        console.print("[yellow]Note:[/yellow] using heuristics path; prefer Bc/Bcw for genomic loop")

    exp, world, fit, wcfg = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    from organism.observer.control import mutations_allowed

    ok, why = mutations_allowed(artifacts)
    if not ok:
        console.print(f"[red]Blocked by operator control:[/red] {why}")
        console.print("[dim]Clear via seo ui -> Control, or delete artifacts/control.json[/dim]")
        raise typer.Exit(3)

    # Safety rail: downgrade Bcw→Bc when diagnose says weights hurt
    eff_abl, safety_why, downgraded = recommend_mutation_ablation(
        artifacts, ablation, force_weights=force_bcw
    )
    if downgraded:
        console.print(f"[yellow]Safety rail:[/yellow] {safety_why}")
        console.print("[dim]Override with --force-bcw if you really want weights path[/dim]")
        ablation = eff_abl
    elif ablation in ("Bcw", "Bw"):
        console.print(f"[dim]safety[/dim] {safety_why}")

    seeds = list(exp.get("eval", {}).get("train_seeds", list(range(8))))
    critic_cfg = dict(exp.get("critic") or {})
    # CLI flag wins over yaml
    use_critic = critic
    sel = (select or "active").strip().lower()
    if sel not in SELECT_POLICIES:
        console.print(f"[red]select must be one of {SELECT_POLICIES}[/red]")
        raise typer.Exit(2)

    store = Store(db)
    try:
        choice = select_and_resolve(
            artifacts,
            store,
            exp,
            policy=sel,
            tournament_k=int(tournament_k),
            parent_id=parent_id,
        )
        parent_dir = Path(choice.path)
        gid = choice.genome_id
        console.print(
            f"[dim]select[/dim] policy={choice.policy} parent={gid} "
            f"fit={choice.fitness} · {choice.reason}"
        )
    except FileNotFoundError as e:
        store.close()
        console.print(f"[red]Parent genome not found:[/red] {e}")
        raise typer.Exit(2)
    # ensure parent row exists (do not force status=active over elite)
    try:
        existing = store.get_genome(gid)
        store.insert_genome(
            genome_id=gid,
            parent_id=(existing or {}).get("parent_id"),
            status=(existing or {}).get("status") or "active",
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
    table.add_row("files", ", ".join(result.files_changed) or "-")
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
        or "-",
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


@app.command("metrics")
def metrics_cmd(
    write: bool = typer.Option(True, "--write/--no-write", help="Write last_pool_metrics.json"),
) -> None:
    """Roll up Phase 3 pool metrics from SQLite (accept rate, critic waste, tokens)."""
    from organism.metrics import collect_pool_metrics, write_metrics_report

    exp, _, _, _ = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    store = Store(db)
    m = collect_pool_metrics(store)
    store.close()

    table = Table(title="Pool metrics")
    table.add_column("metric")
    table.add_column("value")
    table.add_row("mutations", str(m.mutations_total))
    table.add_row(
        "accepted / rejected / failed",
        f"{m.mutations_accepted} / {m.mutations_rejected} / {m.mutations_failed}",
    )
    table.add_row("accept_rate", f"{m.accept_rate:.3f}")
    table.add_row("critic_rejects", str(m.critic_rejects))
    table.add_row("critic_reject_rate", f"{m.critic_reject_rate:.3f}")
    table.add_row("evals_avoided_by_critic", str(m.evals_avoided_by_critic))
    table.add_row("evals_run", str(m.evals_run))
    table.add_row("fitness_rejects", str(m.fitness_rejects))
    table.add_row("critic_fail_open", str(m.critic_fail_open))
    table.add_row("llm_calls", str(m.llm_calls))
    table.add_row("tokens_total", str(m.tokens_total))
    table.add_row(
        "tokens_per_accepted_gain",
        "-" if m.tokens_per_accepted_gain is None else f"{m.tokens_per_accepted_gain:.1f}",
    )
    table.add_row("by_role_tokens", json.dumps(m.by_role_tokens))
    table.add_row("by_critic_code", json.dumps(m.by_critic_code))
    console.print(table)

    if write:
        path = write_metrics_report(m, artifacts / "last_pool_metrics.json")
        console.print(f"[dim]Wrote {path}[/dim]")


@app.command("critic-ab")
def critic_ab_cmd(
    n: int = typer.Option(6, help="Number of synthetic proposals"),
) -> None:
    """
    Offline critic A/B: count evals with critic gate vs always-eval.
    Uses dry_run critic (static + heuristic) — no NIM required.
    """
    from organism.metrics import run_critic_ab

    exp, _, _, _ = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    seed = resolve_path(exp.get("paths", {}).get("seed_genome", "genomes/seed"))
    pol = (seed / "policy.py").read_text(encoding="utf-8")
    heur = (seed / "heuristics.py").read_text(encoding="utf-8")

    proposals: list[dict] = []
    # safe small tweak
    pol_safe = pol.replace("self.rng.random() < 0.7", "self.rng.random() < 0.8")
    proposals.append(
        {"rationale": "slightly greedier chase", "files": {"policy.py": pol_safe}}
    )
    # hostile imports (should static-reject)
    proposals.append(
        {
            "rationale": "exfil",
            "files": {
                "policy.py": (
                    "import os\nclass Policy:\n    def reset(self,s): pass\n"
                    "    def act(self,o): pass\n    def on_step_result(self,r): pass\n"
                )
            },
        }
    )
    proposals.append(
        {
            "rationale": "kernel",
            "files": {
                "policy.py": (
                    "from organism.config import nim_config\nclass Policy:\n"
                    "    def reset(self,s): pass\n    def act(self,o): pass\n"
                    "    def on_step_result(self,r): pass\n"
                )
            },
        }
    )
    proposals.append(
        {
            "rationale": "subprocess",
            "files": {
                "policy.py": (
                    "import subprocess\nclass Policy:\n    def reset(self,s): pass\n"
                    "    def act(self,o): pass\n    def on_step_result(self,r): pass\n"
                )
            },
        }
    )
    # empty
    proposals.append({"rationale": "", "files": {}})
    # another safe
    heur2 = heur + "\n# tweak\n"
    proposals.append(
        {"rationale": "comment heuristics", "files": {"heuristics.py": heur2, "policy.py": pol}}
    )
    proposals = proposals[: max(1, n)]

    report = run_critic_ab(proposals, parent_fitness=10.0)
    table = Table(title="Critic A/B (dry)")
    table.add_column("field")
    table.add_column("value")
    table.add_row("n_proposals", str(report.n_proposals))
    table.add_row("without_critic_evals", str(report.without_critic_evals))
    table.add_row("with_critic_evals", str(report.with_critic_evals))
    table.add_row("evals_saved", str(report.evals_saved))
    table.add_row("critic_reject_rate", f"{report.critic_reject_rate:.3f}")
    table.add_row("static_rejects", str(report.static_rejects))
    table.add_row("taxonomy", json.dumps(report.taxonomy))
    table.add_row("notes", report.notes)
    console.print(table)

    out = artifacts / "last_critic_ab.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    console.print(f"[dim]Wrote {out}[/dim]")


@app.command("watch")
def watch_cmd(
    seed: int = typer.Option(0, help="Episode seed"),
    ablation: str = typer.Option("Bc", help="B0 / Bw / Bc / Bcw"),
    genome: str = typer.Option("", help="Genome dir (default: active or seed)"),
    weights: str = typer.Option("", help="Checkpoint id/path/latest/best for Bw/Bcw"),
    multi: int = typer.Option(
        0,
        "--multi",
        help="Multi-agent same-map: N agents (2–6). Uses active+elites+seed. Viz only.",
    ),
    agents: str = typer.Option(
        "",
        help="Comma-separated genome dirs or ids for multi mode (overrides --multi count)",
    ),
    gif: str = typer.Option(
        "artifacts/replays/last_watch.gif",
        help="Output GIF path (empty to skip)",
    ),
) -> None:
    """Record host episode GIF — single agent or multi-agent same-map (viz only)."""
    from organism.checkpoints import resolve_checkpoint_path
    from organism.elites import list_elites, resolve_genome_dir
    from organism.genome_loader import make_policy_factory
    from organism.mutation import resolve_parent_genome
    from organism.multiagent import multi_replay_to_gif, record_multi_episode
    from organism.replay import record_episode, replay_to_gif

    exp, world, fit, wcfg = _load_cfgs()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))

    # --- multi-agent path ---
    agent_specs: list[tuple[str, Path]] = []
    if agents.strip():
        store = Store(db)
        for part in agents.split(","):
            part = part.strip()
            if not part:
                continue
            p = Path(part)
            if p.exists() and (p / "policy.py").exists():
                agent_specs.append((p.name, p))
            else:
                try:
                    path, gid = resolve_genome_dir(artifacts, part, store=store)
                    agent_specs.append((gid, path))
                except Exception as e:
                    store.close()
                    console.print(f"[red]agent {part}: {e}[/red]")
                    raise typer.Exit(2)
        store.close()
    elif multi and int(multi) >= 2:
        store = Store(db)
        # collect distinct paths: active, elites, seed
        seen: set[str] = set()
        try:
            gdir, gid = resolve_parent_genome(exp, store=store)
            agent_specs.append((gid, gdir))
            seen.add(str(gdir))
        except Exception:
            pass
        for e in list_elites(artifacts):
            p = Path(str(e.get("path") or ""))
            gid = str(e.get("genome_id") or p.name)
            if p.exists() and str(p) not in seen:
                agent_specs.append((gid, p))
                seen.add(str(p))
            if len(agent_specs) >= int(multi):
                break
        seed_p = resolve_path(exp.get("paths", {}).get("seed_genome", "genomes/seed"))
        if len(agent_specs) < int(multi) and seed_p.exists():
            # duplicate seed with different ids for pad
            while len(agent_specs) < int(multi):
                agent_specs.append((f"g_seed_{len(agent_specs)}", seed_p))
        store.close()
        agent_specs = agent_specs[: int(multi)]

    if agent_specs and len(agent_specs) >= 2:
        policies = []
        for gid, gdir in agent_specs:
            factory = make_policy_factory(
                gdir,
                ablation=ablation,
                weight_cfg=wcfg,
                force_train=False,
            )
            policies.append((gid, factory()))
        console.print(
            f"[cyan]Watch multi[/cyan] agents={len(policies)} "
            f"ids={[g for g, _ in policies]} seed={seed}"
        )
        mrep = record_multi_episode(
            policies,
            world,
            seed=seed,
            ablation=ablation,
            episode_timeout_s=float(fit.episode_timeout_s or 30),
        )
        if mrep.error:
            console.print(f"[red]{mrep.error}[/red]")
            raise typer.Exit(1)
        console.print(f"frames={len(mrep.frames)} final={mrep.final}")
        if gif:
            out = resolve_path(gif)
            if "last_watch" in str(out):
                out = resolve_path("artifacts/replays/last_watch_multi.gif")
            multi_replay_to_gif(mrep, out, cell=14, duration_ms=80, show_trail=True)
            console.print(f"[green]GIF[/green] {out}")
        return

    # --- single agent ---
    if genome:
        gdir = Path(genome)
        gid = gdir.name
    else:
        gdir, gid = resolve_parent_genome(exp)
    wpath = None
    if weights and ablation in ("Bw", "Bcw"):
        wpath = resolve_checkpoint_path(artifacts, weights)
    factory = make_policy_factory(
        gdir,
        ablation=ablation,
        weight_cfg=wcfg,
        weight_path=wpath,
        force_train=False,
    )
    console.print(
        f"[cyan]Watch[/cyan] genome={gid} path={gdir} ablation={ablation} seed={seed}"
    )
    rep = record_episode(
        factory(),
        world,
        seed=seed,
        train_weights=False,
        episode_timeout_s=float(fit.episode_timeout_s or 30),
        genome_id=gid,
        ablation=ablation,
        fit_cfg=fit,
    )
    if rep.error:
        console.print(f"[red]{rep.error}[/red]")
        raise typer.Exit(1)
    console.print(
        f"frames={len(rep.frames)} food={rep.summary.food_collected} "
        f"ticks={rep.summary.ticks_survived} death={rep.summary.death_reason} "
        f"score={rep.summary.score:.4f}"
    )
    if gif:
        out = resolve_path(gif)
        replay_to_gif(rep, out, cell=14, duration_ms=80, show_trail=True)
        console.print(f"[green]GIF[/green] {out}")


@app.command("doctor")
def doctor_cmd(
    strict_docker: bool = typer.Option(
        False,
        "--strict-docker",
        help="Fail if Docker unavailable even when sandbox.require_docker is soft",
    ),
) -> None:
    """Phase 6: environment / artifacts / docker health check."""
    from organism.doctor import run_doctor

    report = run_doctor(require_docker=True if strict_docker else None)
    table = Table(title="seo doctor")
    table.add_column("check")
    table.add_column("ok")
    table.add_column("severity")
    table.add_column("detail")
    for c in report.checks:
        mark = "yes" if c.ok else "NO"
        color = "green" if c.ok else ("red" if c.severity == "error" else "yellow")
        table.add_row(c.name, f"[{color}]{mark}[/{color}]", c.severity, c.detail[:80])
    console.print(table)
    console.print(
        f"{'[green]OK[/green]' if report.ok else '[red]ISSUES[/red]'} · "
        "artifacts/last_doctor_report.json"
    )
    if not report.ok:
        raise typer.Exit(1)


@app.command("ui")
def ui_cmd(
    port: int = typer.Option(8501, help="Streamlit port"),
    browser: bool = typer.Option(True, "--browser/--no-browser"),
) -> None:
    """Phase 4 observer UI (Streamlit) — read-mostly operator dashboard."""
    import subprocess
    import sys

    try:
        import streamlit  # noqa: F401
    except ImportError:
        console.print(
            '[red]streamlit not installed[/red] - run: pip install -e ".[ui]"'
        )
        raise typer.Exit(2)

    app_path = Path(__file__).resolve().parent / "observer" / "app.py"
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app_path),
        "--server.port",
        str(port),
        "--server.headless",
        "true" if not browser else "false",
    ]
    console.print(f"[cyan]Observer UI[/cyan] {app_path} | http://localhost:{port}")
    raise SystemExit(subprocess.call(cmd))


@app.callback()
def main() -> None:
    """self-evolving-organism CLI."""
    pass


if __name__ == "__main__":
    app()

