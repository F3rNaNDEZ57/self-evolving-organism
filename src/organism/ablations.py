"""Full B0 / Bw / Bc / Bcw ablation suite with holdout δ report."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from organism.evaluator import EvalResult, FitnessConfig, evaluate, run_episode
from organism.genome_loader import copy_genome, make_policy_factory
from organism.mutation import run_mutation_cycle
from organism.nim_client import NimClient
from organism.persistence import Store
from organism.weights import LinearScorer, WeightConfig
from organism.world import WorldConfig

AblationName = Literal["B0", "Bw", "Bc", "Bcw"]


@dataclass
class ArmResult:
    ablation: str
    genome_id: str
    genome_path: str
    train_fitness: float
    train_mean: float
    train_std: float
    holdout_fitness: float
    holdout_mean: float
    holdout_std: float
    mutations_attempted: int = 0
    mutations_accepted: int = 0
    weight_path: str | None = None
    notes: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AblationReport:
    run_id: str
    delta_success: float
    delta_holdout_bcw_minus_b0: float
    success: bool  # holdout Bcw >= B0 + δ
    arms: dict[str, ArmResult]
    comparisons: dict[str, float]
    config_snapshot: dict[str, Any]
    created_at: float
    delta_mean: float | None = None
    delta_std: float | None = None
    repeat_deltas: list[float] = field(default_factory=list)
    manifest_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "delta_success": self.delta_success,
            "delta_holdout_bcw_minus_b0": self.delta_holdout_bcw_minus_b0,
            "success": self.success,
            "arms": {k: v.to_dict() for k, v in self.arms.items()},
            "comparisons": self.comparisons,
            "config_snapshot": self.config_snapshot,
            "created_at": self.created_at,
            "delta_mean": self.delta_mean,
            "delta_std": self.delta_std,
            "repeat_deltas": self.repeat_deltas,
            "manifest_path": self.manifest_path,
        }


def _uid(prefix: str = "run") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _eval(
    genome_dir: Path,
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    seeds: list[int],
    ablation: str,
    *,
    train_weights: bool | None = None,
    weight_path: Path | None = None,
) -> EvalResult:
    train = ablation in ("Bw", "Bcw") if train_weights is None else train_weights
    factory = make_policy_factory(
        genome_dir,
        ablation=ablation,
        weight_cfg=wcfg,
        weight_path=weight_path,
        force_train=train,
    )
    return evaluate(factory, world, fit, seeds, train_weights=train)


def train_weights_on_seed(
    genome_dir: Path,
    world: WorldConfig,
    wcfg: WeightConfig,
    train_seeds: list[int],
    *,
    passes: int = 2,
    out_path: Path,
    artifacts_dir: Path | None = None,
    genome_id: str = "g_seed",
    fit_cfg: FitnessConfig | None = None,
    store: Store | None = None,
) -> Path:
    """Train a single LinearScorer across episodes; save full checkpoint (+ sidecar)."""
    from organism.checkpoints import save_checkpoint, train_and_checkpoint

    art = Path(artifacts_dir) if artifacts_dir is not None else Path(out_path).parent.parent
    meta = train_and_checkpoint(
        genome_dir=genome_dir,
        world=world,
        wcfg=wcfg,
        train_seeds=train_seeds,
        artifacts_dir=art,
        genome_id=genome_id,
        passes=passes,
        ablation="Bw",
        label=Path(out_path).stem,
        fit_cfg=fit_cfg,
        eval_seeds=train_seeds if fit_cfg is not None else None,
    )
    # also copy/link canonical path expected by caller if different
    src = Path(meta.path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != out_path.resolve():
        import shutil

        shutil.copy2(src, out_path)
        # sidecar next to alias path
        side = src.with_suffix(".json")
        if side.exists():
            shutil.copy2(side, out_path.with_suffix(".json"))
    if store is not None:
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
    return Path(meta.path)


def run_code_mutations(
    *,
    start_dir: Path,
    start_id: str,
    artifacts_dir: Path,
    store: Store,
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    train_seeds: list[int],
    ablation: str,
    max_mutations: int,
    dry_run: bool,
    client: NimClient | None,
) -> tuple[Path, str, int, int]:
    """
    Run up to max_mutations cycles. Returns (final_dir, final_id, attempted, accepted).
    """
    parent_dir = start_dir
    parent_id = start_id
    attempted = 0
    accepted = 0
    for i in range(max_mutations):
        attempted += 1
        from organism.sandbox import SandboxConfig

        sb = SandboxConfig(
            mode="host" if dry_run else "docker",
            episode_isolation=not dry_run,
            require_docker=not dry_run,
        )
        result = run_mutation_cycle(
            parent_dir=parent_dir,
            artifacts_dir=artifacts_dir,
            store=store,
            world=world,
            fit=fit,
            wcfg=wcfg,
            train_seeds=train_seeds,
            ablation=ablation,
            parent_genome_id=parent_id,
            client=client,
            dry_run=dry_run,
            sandbox_cfg=sb,
            force_host_eval=dry_run,
            critic_cfg={"enabled": True},
        )
        if result.decision == "accepted":
            accepted += 1
            parent_dir = Path(result.candidate_path)
            parent_id = result.candidate_genome_id
        elif result.decision == "failed":
            # keep parent; continue
            continue
        # rejected: keep parent
    return parent_dir, parent_id, attempted, accepted


def run_arm_b0(
    seed_dir: Path,
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    train_seeds: list[int],
    holdout_seeds: list[int],
    store: Store,
    run_id: str,
) -> ArmResult:
    gid = f"{run_id}_B0"
    store.insert_genome(genome_id=gid, status="active", ablation="B0", artifact_path=str(seed_dir))
    tr = _eval(seed_dir, world, fit, wcfg, train_seeds, "B0", train_weights=False)
    ho = _eval(seed_dir, world, fit, wcfg, holdout_seeds, "B0", train_weights=False)
    store.insert_evaluation(gid, tr.fitness, tr.mean_score, tr.std_score, tr.seeds, tr.episodes)
    store.insert_evaluation(gid, ho.fitness, ho.mean_score, ho.std_score, ho.seeds, ho.episodes)
    return ArmResult(
        ablation="B0",
        genome_id=gid,
        genome_path=str(seed_dir),
        train_fitness=tr.fitness,
        train_mean=tr.mean_score,
        train_std=tr.std_score,
        holdout_fitness=ho.fitness,
        holdout_mean=ho.mean_score,
        holdout_std=ho.std_score,
        notes="fixed seed, no weights",
    )


def run_arm_bw(
    seed_dir: Path,
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    train_seeds: list[int],
    holdout_seeds: list[int],
    store: Store,
    artifacts_dir: Path,
    run_id: str,
    train_passes: int,
) -> ArmResult:
    gid = f"{run_id}_Bw"
    wpath = artifacts_dir / "weights" / f"{gid}.npz"
    ckpt_path = train_weights_on_seed(
        seed_dir,
        world,
        wcfg,
        train_seeds,
        passes=train_passes,
        out_path=wpath,
        artifacts_dir=artifacts_dir,
        genome_id=gid,
        fit_cfg=fit,
        store=store,
    )
    store.insert_genome(genome_id=gid, status="active", ablation="Bw", artifact_path=str(seed_dir))
    # final evals: use trained weights, no further training
    tr = _eval(seed_dir, world, fit, wcfg, train_seeds, "Bw", train_weights=False, weight_path=ckpt_path)
    ho = _eval(seed_dir, world, fit, wcfg, holdout_seeds, "Bw", train_weights=False, weight_path=ckpt_path)
    store.insert_evaluation(gid, tr.fitness, tr.mean_score, tr.std_score, tr.seeds, tr.episodes)
    store.insert_evaluation(gid, ho.fitness, ho.mean_score, ho.std_score, ho.seeds, ho.episodes)
    return ArmResult(
        ablation="Bw",
        genome_id=gid,
        genome_path=str(seed_dir),
        train_fitness=tr.fitness,
        train_mean=tr.mean_score,
        train_std=tr.std_score,
        holdout_fitness=ho.fitness,
        holdout_mean=ho.mean_score,
        holdout_std=ho.std_score,
        weight_path=str(ckpt_path),
        notes=f"weights trained passes={train_passes}",
    )


def run_arm_code(
    *,
    ablation: str,
    seed_dir: Path,
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    train_seeds: list[int],
    holdout_seeds: list[int],
    store: Store,
    artifacts_dir: Path,
    run_id: str,
    max_mutations: int,
    dry_run: bool,
    client: NimClient | None,
    train_passes: int = 2,
    b0_holdout: float | None = None,
) -> ArmResult:
    assert ablation in ("Bc", "Bcw")
    # private working copy so mutations don't stomp shared seed
    start_id = f"{run_id}_{ablation}_start"
    start_dir = artifacts_dir / "genomes" / start_id
    if start_dir.exists():
        import shutil

        shutil.rmtree(start_dir)
    copy_genome(seed_dir, start_dir)
    store.insert_genome(
        genome_id=start_id,
        status="active",
        ablation=ablation,
        artifact_path=str(start_dir),
    )

    final_dir, final_id, attempted, accepted = run_code_mutations(
        start_dir=start_dir,
        start_id=start_id,
        artifacts_dir=artifacts_dir,
        store=store,
        world=world,
        fit=fit,
        wcfg=wcfg,
        train_seeds=train_seeds,
        ablation=ablation,
        max_mutations=max_mutations,
        dry_run=dry_run,
        client=client,
    )

    # optional: train weights after mutations for Bcw final snapshot
    weight_path = None
    attribution: dict[str, float] = {}
    if ablation == "Bcw":
        wpath = artifacts_dir / "weights" / f"{final_id}.npz"
        ckpt_path = train_weights_on_seed(
            final_dir,
            world,
            wcfg,
            train_seeds,
            passes=int(train_passes),
            out_path=wpath,
            artifacts_dir=artifacts_dir,
            genome_id=final_id,
            fit_cfg=fit,
            store=store,
        )
        weight_path = ckpt_path
        tr = _eval(
            final_dir, world, fit, wcfg, train_seeds, "Bcw", train_weights=False, weight_path=ckpt_path
        )
        ho = _eval(
            final_dir,
            world,
            fit,
            wcfg,
            holdout_seeds,
            "Bcw",
            train_weights=False,
            weight_path=ckpt_path,
        )
        # D5 rule 5: code-only re-eval (weights zeroed / not loaded) vs full Bcw
        ho_code = _eval(
            final_dir,
            world,
            fit,
            wcfg,
            holdout_seeds,
            "Bc",
            train_weights=False,
            weight_path=None,
        )
        attribution["holdout_code_only"] = ho_code.fitness
        attribution["holdout_with_weights"] = ho.fitness
        attribution["fitness_gain_from_weights"] = ho.fitness - ho_code.fitness
        if b0_holdout is not None:
            attribution["fitness_gain_from_code"] = ho_code.fitness - float(b0_holdout)
            attribution["fitness_gain_total_vs_b0"] = ho.fitness - float(b0_holdout)
    else:
        tr = _eval(final_dir, world, fit, wcfg, train_seeds, "Bc", train_weights=False)
        ho = _eval(final_dir, world, fit, wcfg, holdout_seeds, "Bc", train_weights=False)

    store.insert_evaluation(final_id, tr.fitness, tr.mean_score, tr.std_score, tr.seeds, tr.episodes)
    store.insert_evaluation(final_id, ho.fitness, ho.mean_score, ho.std_score, ho.seeds, ho.episodes)

    return ArmResult(
        ablation=ablation,
        genome_id=final_id,
        genome_path=str(final_dir),
        train_fitness=tr.fitness,
        train_mean=tr.mean_score,
        train_std=tr.std_score,
        holdout_fitness=ho.fitness,
        holdout_mean=ho.mean_score,
        holdout_std=ho.std_score,
        mutations_attempted=attempted,
        mutations_accepted=accepted,
        weight_path=str(weight_path) if weight_path else None,
        notes=f"mutations accepted {accepted}/{attempted}"
        + (f"; train_passes={train_passes}" if ablation == "Bcw" else ""),
        meta=attribution,
    )


def _shift_seeds(seeds: list[int], offset: int) -> list[int]:
    return [int(s) + int(offset) for s in seeds]


def _run_single_ablation_pass(
    *,
    run_id: str,
    selected: list[str],
    suite_seed: Path,
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    train_seeds: list[int],
    holdout_seeds: list[int],
    store: Store,
    artifacts_dir: Path,
    muts: int,
    train_passes: int,
    use_dry: bool,
    client: NimClient | None,
) -> dict[str, ArmResult]:
    results: dict[str, ArmResult] = {}
    if "B0" in selected:
        results["B0"] = run_arm_b0(
            suite_seed, world, fit, wcfg, train_seeds, holdout_seeds, store, run_id
        )
    b0_h = results["B0"].holdout_fitness if "B0" in results else None
    if "Bw" in selected:
        results["Bw"] = run_arm_bw(
            suite_seed,
            world,
            fit,
            wcfg,
            train_seeds,
            holdout_seeds,
            store,
            artifacts_dir,
            run_id,
            train_passes,
        )
    if "Bc" in selected:
        results["Bc"] = run_arm_code(
            ablation="Bc",
            seed_dir=suite_seed,
            world=world,
            fit=fit,
            wcfg=wcfg,
            train_seeds=train_seeds,
            holdout_seeds=holdout_seeds,
            store=store,
            artifacts_dir=artifacts_dir,
            run_id=run_id,
            max_mutations=muts,
            dry_run=use_dry,
            client=client,
            train_passes=train_passes,
            b0_holdout=b0_h,
        )
    if "Bcw" in selected:
        results["Bcw"] = run_arm_code(
            ablation="Bcw",
            seed_dir=suite_seed,
            world=world,
            fit=fit,
            wcfg=wcfg,
            train_seeds=train_seeds,
            holdout_seeds=holdout_seeds,
            store=store,
            artifacts_dir=artifacts_dir,
            run_id=run_id,
            max_mutations=muts,
            dry_run=use_dry,
            client=client,
            train_passes=train_passes,
            b0_holdout=b0_h,
        )
    return results


def run_ablation_suite(
    *,
    exp: dict[str, Any],
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    store: Store,
    artifacts_dir: Path,
    seed_dir: Path,
    quick: bool = False,
    dry_run: bool | None = None,
    arms: list[str] | None = None,
    max_mutations: int | None = None,
    client: NimClient | None = None,
    repeats: int | None = None,
) -> AblationReport:
    """
    Run B0/Bw/Bc/Bcw (subset via arms=) and compute holdout δ success.
    repeats=K runs independent seed-offset trajectories and reports mean±std on δ.
    Recommend K≥3 and max_mutations≥3 for a defensible claim (free-tier RPM limited).
    """
    suite = exp.get("ablation_suite", {})
    eval_cfg = exp.get("eval", {})
    genomic = exp.get("genomic", {})

    if quick:
        q = suite.get("quick", {})
        train_seeds = list(q.get("train_seeds", [0, 1, 2]))
        holdout_seeds = list(q.get("holdout_seeds", [100, 101, 102]))
        muts = int(q.get("max_mutations", 1))
        train_passes = int(q.get("train_passes", 1))
        use_dry = True if dry_run is None else dry_run
        k_rep = int(repeats if repeats is not None else q.get("repeats", 1))
    else:
        train_seeds = list(eval_cfg.get("train_seeds", list(range(8))))
        holdout_seeds = list(eval_cfg.get("holdout_seeds", list(range(100, 108))))
        muts = int(max_mutations if max_mutations is not None else genomic.get("max_mutations", 3))
        # default 3 mutations for full suite practicality; config can set 30
        if max_mutations is None and "max_mutations" not in genomic:
            muts = int(suite.get("max_mutations", 3))
        train_passes = int(suite.get("train_passes", 2))
        use_dry = False if dry_run is None else dry_run
        k_rep = int(repeats if repeats is not None else suite.get("repeats", 1))
    k_rep = max(1, k_rep)

    selected = arms or ["B0", "Bw", "Bc", "Bcw"]
    run_id = _uid("abl")
    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # fresh seed copy for suite
    suite_seed = artifacts_dir / "genomes" / f"{run_id}_seed"
    if suite_seed.exists():
        import shutil

        shutil.rmtree(suite_seed)
    copy_genome(seed_dir, suite_seed)

    store.log_event(
        "ablation_suite_start",
        {
            "run_id": run_id,
            "arms": selected,
            "quick": quick,
            "dry_run": use_dry,
            "train_seeds": train_seeds,
            "holdout_seeds": holdout_seeds,
            "max_mutations": muts,
            "repeats": k_rep,
            "train_passes": train_passes,
        },
    )

    # Reproducibility package
    from organism.config import ROOT, nim_config
    from organism.manifest import build_manifest, write_manifest

    try:
        pins = nim_config().get("models", {})
    except Exception:
        pins = {}
    manifest = build_manifest(
        run_id=run_id,
        run_kind="ablation",
        root=ROOT,
        exp=exp,
        world={
            "grid": [world.height, world.width],
            "T": world.T,
            "food_density": world.food_density,
            "vision": world.vision,
        },
        fitness={
            "lambda_std": fit.lambda_std,
            "epsilon_accept": fit.epsilon_accept,
            "delta_success": fit.delta_success,
            "episode_timeout_s": getattr(fit, "episode_timeout_s", 5.0),
        },
        weights={
            "alpha": wcfg.alpha,
            "init_std": wcfg.init_std,
            "clip_abs": wcfg.clip_abs,
        },
        nim_pins={str(k): str(v) for k, v in pins.items()},
        rng_roots={
            "train_seeds": train_seeds,
            "holdout_seeds": holdout_seeds,
            "repeats": k_rep,
            "seed_offset_per_repeat": 10_000,
        },
        extra={"arms": selected, "quick": quick, "dry_run": use_dry, "max_mutations": muts},
    )
    man_path = write_manifest(artifacts_dir / "ablations" / f"{run_id}_manifest.json", manifest)

    repeat_deltas: list[float] = []
    results: dict[str, ArmResult] = {}
    for rep in range(k_rep):
        # Independent trajectory: offset seeds so food maps / RNG differ
        offset = rep * 10_000
        ts = _shift_seeds(train_seeds, offset)
        hs = _shift_seeds(holdout_seeds, offset)
        rep_id = run_id if k_rep == 1 else f"{run_id}_r{rep}"
        results = _run_single_ablation_pass(
            run_id=rep_id,
            selected=selected,
            suite_seed=suite_seed,
            world=world,
            fit=fit,
            wcfg=wcfg,
            train_seeds=ts,
            holdout_seeds=hs,
            store=store,
            artifacts_dir=artifacts_dir,
            muts=muts,
            train_passes=train_passes,
            use_dry=use_dry,
            client=client,
        )
        if "B0" in results and "Bcw" in results:
            repeat_deltas.append(results["Bcw"].holdout_fitness - results["B0"].holdout_fitness)

    b0_h = results["B0"].holdout_fitness if "B0" in results else 0.0
    bcw_h = results["Bcw"].holdout_fitness if "Bcw" in results else 0.0
    delta = bcw_h - b0_h
    delta_thr = float(fit.delta_success)
    if repeat_deltas:
        import numpy as np

        delta_mean = float(np.mean(repeat_deltas))
        delta_std = float(np.std(repeat_deltas, ddof=0)) if len(repeat_deltas) > 1 else 0.0
        # Success: mean δ meets threshold (primary) or last-run for K=1
        success = delta_mean >= delta_thr
        delta = delta_mean
    else:
        delta_mean = None
        delta_std = None
        success = ("B0" in results and "Bcw" in results) and (bcw_h >= b0_h + delta_thr)

    comparisons: dict[str, float] = {}
    if "B0" in results and "Bw" in results:
        comparisons["holdout_Bw_minus_B0"] = results["Bw"].holdout_fitness - results["B0"].holdout_fitness
    if "B0" in results and "Bc" in results:
        comparisons["holdout_Bc_minus_B0"] = results["Bc"].holdout_fitness - results["B0"].holdout_fitness
    if "B0" in results and "Bcw" in results:
        comparisons["holdout_Bcw_minus_B0"] = (
            results["Bcw"].holdout_fitness - results["B0"].holdout_fitness
        )
    if "Bw" in results and "Bcw" in results:
        comparisons["holdout_Bcw_minus_Bw"] = (
            results["Bcw"].holdout_fitness - results["Bw"].holdout_fitness
        )
    if "Bc" in results and "Bcw" in results:
        comparisons["holdout_Bcw_minus_Bc"] = (
            results["Bcw"].holdout_fitness - results["Bc"].holdout_fitness
        )
    if "Bcw" in results and results["Bcw"].meta:
        for k, v in results["Bcw"].meta.items():
            if isinstance(v, (int, float)):
                comparisons[f"bcw_{k}"] = float(v)

    report = AblationReport(
        run_id=run_id,
        delta_success=delta_thr,
        delta_holdout_bcw_minus_b0=delta,
        success=success,
        arms=results,
        comparisons=comparisons,
        config_snapshot={
            "quick": quick,
            "dry_run": use_dry,
            "train_seeds": train_seeds,
            "holdout_seeds": holdout_seeds,
            "max_mutations": muts,
            "train_passes": train_passes,
            "repeats": k_rep,
            "epsilon_accept": fit.epsilon_accept,
            "delta_success": delta_thr,
            "world_T": world.T,
            "grid": [world.height, world.width],
            "manifest_path": str(man_path),
        },
        created_at=time.time(),
        delta_mean=delta_mean,
        delta_std=delta_std,
        repeat_deltas=repeat_deltas,
        manifest_path=str(man_path),
    )

    out_dir = artifacts_dir / "ablations"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run_id}.json"
    out_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    latest = artifacts_dir / "last_ablation_report.json"
    latest.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

    store.log_event(
        "ablation_suite_end",
        {
            "run_id": run_id,
            "success": success,
            "delta_holdout_bcw_minus_b0": delta,
            "report_path": str(out_path),
        },
    )
    return report
