"""Continuous evolution loop: episode budget + schedule/plateau mutation triggers."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from organism.evaluator import FitnessConfig, episode_score, evaluate, run_episode
from organism.genome_loader import make_policy_factory
from organism.mutation import resolve_parent_genome, run_mutation_cycle
from organism.nim_client import NimClient
from organism.persistence import Store
from organism.weights import WeightConfig
from organism.world import WorldConfig


@dataclass
class EvolveConfig:
    mutate_every_episodes: int = 10
    plateau_episodes: int = 20
    max_mutations: int = 30
    ablation: str = "Bc"
    dry_run: bool = False
    # how many train-seed evals between trigger checks (1 = every eval cycle)
    eval_every: int = 1
    # plateau: no improvement greater than this absolute delta over the window
    plateau_epsilon: float = 0.01

    @classmethod
    def from_exp(cls, exp: dict[str, Any], *, dry_run: bool = False, ablation: str = "Bc") -> EvolveConfig:
        g = exp.get("genomic", {})
        evo = exp.get("evolve", {})
        return cls(
            mutate_every_episodes=int(evo.get("mutate_every_episodes", g.get("mutate_every_episodes", 10))),
            plateau_episodes=int(evo.get("plateau_episodes", g.get("plateau_episodes", 20))),
            max_mutations=int(evo.get("max_mutations", g.get("max_mutations", 30))),
            ablation=ablation,
            dry_run=dry_run,
            eval_every=int(evo.get("eval_every", 1)),
            plateau_epsilon=float(evo.get("plateau_epsilon", 0.01)),
        )


@dataclass
class EvolveEvent:
    kind: str  # eval | mutate_schedule | mutate_plateau | skip
    episode_index: int
    fitness: float | None = None
    mutation_id: str | None = None
    decision: str | None = None
    reason: str = ""
    genome_id: str | None = None


@dataclass
class EvolveReport:
    run_id: str
    ablation: str
    dry_run: bool
    episodes_run: int
    mutations_attempted: int
    mutations_accepted: int
    mutations_rejected: int
    mutations_failed: int
    start_genome_id: str
    final_genome_id: str
    final_genome_path: str
    fitness_history: list[float]
    events: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _uid(prefix: str = "evo") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def detect_trigger(
    *,
    episodes_since_mutation: int,
    fitness_history: list[float],
    cfg: EvolveConfig,
) -> tuple[bool, str]:
    """Return (should_mutate, reason). Schedule checked first, then plateau."""
    if episodes_since_mutation >= cfg.mutate_every_episodes:
        return True, "schedule"
    p = cfg.plateau_episodes
    if p > 0 and len(fitness_history) >= p:
        window = fitness_history[-p:]
        # plateau if best in window is not meaningfully above the first value
        # and range is tiny (no progress)
        span = max(window) - min(window)
        improved = max(window) - window[0]
        if span <= cfg.plateau_epsilon and improved <= cfg.plateau_epsilon:
            return True, "plateau"
        # also plateau if last p values never beat historical best before window
        if len(fitness_history) > p:
            prior_best = max(fitness_history[:-p])
            if max(window) <= prior_best + cfg.plateau_epsilon:
                return True, "plateau"
    return False, ""


def run_evolve(
    *,
    exp: dict[str, Any],
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    store: Store,
    artifacts_dir: Path,
    max_eval_cycles: int,
    cfg: EvolveConfig,
    client: NimClient | None = None,
    train_seeds: list[int] | None = None,
) -> EvolveReport:
    """
    Run up to max_eval_cycles fitness evaluations on the active genome.
    Between cycles, fire mutation when schedule or plateau triggers fire,
    until max_mutations is hit.
    """
    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    seeds = train_seeds or list(exp.get("eval", {}).get("train_seeds", list(range(8))))
    run_id = _uid("evo")

    parent_dir, parent_id = resolve_parent_genome(exp)
    # Ensure genome row
    store.insert_genome(
        genome_id=parent_id,
        status="active",
        ablation=cfg.ablation,
        artifact_path=str(parent_dir),
    )

    fitness_history: list[float] = []
    events: list[dict[str, Any]] = []
    episodes_run = 0  # count of seed-evals (each multi-seed eval counts as len(seeds) episodes)
    eval_cycles = 0
    episodes_since_mut = 0
    mut_attempted = mut_accepted = mut_rejected = mut_failed = 0

    store.log_event(
        "evolve_start",
        {
            "run_id": run_id,
            "ablation": cfg.ablation,
            "dry_run": cfg.dry_run,
            "max_eval_cycles": max_eval_cycles,
            "mutate_every_episodes": cfg.mutate_every_episodes,
            "plateau_episodes": cfg.plateau_episodes,
            "max_mutations": cfg.max_mutations,
            "parent_id": parent_id,
        },
    )

    start_id = parent_id
    while eval_cycles < max_eval_cycles:
        # 1) Evaluate current genome (train seeds)
        factory = make_policy_factory(
            parent_dir,
            ablation=cfg.ablation,
            weight_cfg=wcfg,
            force_train=cfg.ablation in ("Bw", "Bcw"),
        )
        train = cfg.ablation in ("Bw", "Bcw")
        result = evaluate(factory, world, fit, seeds, train_weights=train)
        store.insert_evaluation(
            parent_id,
            result.fitness,
            result.mean_score,
            result.std_score,
            result.seeds,
            result.episodes,
        )
        fitness_history.append(result.fitness)
        eval_cycles += 1
        episodes_run += len(seeds)
        episodes_since_mut += len(seeds)

        events.append(
            asdict(
                EvolveEvent(
                    kind="eval",
                    episode_index=episodes_run,
                    fitness=result.fitness,
                    genome_id=parent_id,
                    reason=f"cycle={eval_cycles}",
                )
            )
        )

        # 2) Trigger?
        if mut_attempted >= cfg.max_mutations:
            continue

        fire, reason = detect_trigger(
            episodes_since_mutation=episodes_since_mut,
            fitness_history=fitness_history,
            cfg=cfg,
        )
        if not fire:
            continue

        mut_attempted += 1
        from organism.sandbox import SandboxConfig

        sb = SandboxConfig.from_exp(exp)
        mres = run_mutation_cycle(
            parent_dir=parent_dir,
            artifacts_dir=artifacts_dir,
            store=store,
            world=world,
            fit=fit,
            wcfg=wcfg,
            train_seeds=seeds,
            ablation=cfg.ablation if cfg.ablation in ("Bc", "Bcw") else "Bc",
            parent_genome_id=parent_id,
            client=client,
            dry_run=cfg.dry_run,
            sandbox_cfg=sb,
            force_host_eval=cfg.dry_run or sb.mode == "host" or not sb.episode_isolation,
            critic_cfg=dict(exp.get("critic") or {}),
        )
        episodes_since_mut = 0

        if mres.decision == "accepted":
            mut_accepted += 1
            parent_dir = Path(mres.candidate_path)
            parent_id = mres.candidate_genome_id
        elif mres.decision == "rejected":
            mut_rejected += 1
        else:
            mut_failed += 1

        events.append(
            asdict(
                EvolveEvent(
                    kind=f"mutate_{reason}",
                    episode_index=episodes_run,
                    fitness=mres.candidate_fitness,
                    mutation_id=mres.mutation_id,
                    decision=mres.decision,
                    reason=mres.reason,
                    genome_id=parent_id,
                )
            )
        )

    report = EvolveReport(
        run_id=run_id,
        ablation=cfg.ablation,
        dry_run=cfg.dry_run,
        episodes_run=episodes_run,
        mutations_attempted=mut_attempted,
        mutations_accepted=mut_accepted,
        mutations_rejected=mut_rejected,
        mutations_failed=mut_failed,
        start_genome_id=start_id,
        final_genome_id=parent_id,
        final_genome_path=str(parent_dir),
        fitness_history=fitness_history,
        events=events,
        created_at=time.time(),
    )

    out_dir = artifacts_dir / "evolve"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run_id}.json"
    out_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    (artifacts_dir / "last_evolve_report.json").write_text(
        json.dumps(report.to_dict(), indent=2), encoding="utf-8"
    )
    store.log_event(
        "evolve_end",
        {
            "run_id": run_id,
            "mutations_accepted": mut_accepted,
            "mutations_attempted": mut_attempted,
            "final_genome_id": parent_id,
            "report_path": str(out_path),
        },
    )
    return report
