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
from organism.lineages import (
    BudgetConfig,
    global_episodes_ok,
    lineage_can_eval,
    lineage_can_mutate,
    open_lineage_slots,
    pick_lineage,
)
from organism.mutation import run_mutation_cycle
from organism.nim_client import NimClient
from organism.persistence import Store
from organism.selection import select_and_resolve
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
    # Phase 5: parent selection at each mutation trigger
    select: str = "active"  # active | fitness_rank | tournament
    tournament_k: int = 3
    auto_elite_on_accept: bool = False  # promote accepted children into elite archive
    # Phase 5 multi-lineage budgets
    max_lineages: int = 1
    max_eval_cycles_per_lineage: int = 0
    max_mutations_per_lineage: int = 0
    max_episodes_total: int = 0
    lineage_schedule: str = "round_robin"  # round_robin | fitness_rank

    @classmethod
    def from_exp(cls, exp: dict[str, Any], *, dry_run: bool = False, ablation: str = "Bc") -> EvolveConfig:
        g = exp.get("genomic", {})
        evo = exp.get("evolve", {})
        bud = evo.get("budgets", {}) or {}
        return cls(
            mutate_every_episodes=int(evo.get("mutate_every_episodes", g.get("mutate_every_episodes", 10))),
            plateau_episodes=int(evo.get("plateau_episodes", g.get("plateau_episodes", 20))),
            max_mutations=int(evo.get("max_mutations", g.get("max_mutations", 30))),
            ablation=ablation,
            dry_run=dry_run,
            eval_every=int(evo.get("eval_every", 1)),
            plateau_epsilon=float(evo.get("plateau_epsilon", 0.01)),
            select=str(evo.get("select", "active")),
            tournament_k=int(evo.get("tournament_k", 3)),
            auto_elite_on_accept=bool(evo.get("auto_elite_on_accept", False)),
            max_lineages=int(bud.get("max_lineages", evo.get("max_lineages", 1))),
            max_eval_cycles_per_lineage=int(
                bud.get(
                    "max_eval_cycles_per_lineage",
                    evo.get("max_eval_cycles_per_lineage", 0),
                )
            ),
            max_mutations_per_lineage=int(
                bud.get(
                    "max_mutations_per_lineage",
                    evo.get("max_mutations_per_lineage", 0),
                )
            ),
            max_episodes_total=int(
                bud.get("max_episodes_total", evo.get("max_episodes_total", 0))
            ),
            lineage_schedule=str(
                bud.get("schedule", evo.get("lineage_schedule", "round_robin"))
            ),
        )

    def budget_config(self) -> BudgetConfig:
        return BudgetConfig(
            max_lineages=self.max_lineages,
            max_eval_cycles_per_lineage=self.max_eval_cycles_per_lineage,
            max_mutations_per_lineage=self.max_mutations_per_lineage,
            max_episodes_total=self.max_episodes_total,
            schedule=self.lineage_schedule,
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
    max_lineages: int = 1
    lineage_schedule: str = "round_robin"
    lineages: list[dict[str, Any]] = field(default_factory=list)
    budgets: dict[str, Any] = field(default_factory=dict)

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
    Run up to max_eval_cycles fitness evaluations.
    max_lineages=1 → classic single-lineage evolve.
    max_lineages>1 → multi-lineage with per-slot budgets + schedule.
    """
    if int(cfg.max_lineages or 1) > 1:
        return run_evolve_population(
            exp=exp,
            world=world,
            fit=fit,
            wcfg=wcfg,
            store=store,
            artifacts_dir=artifacts_dir,
            max_eval_cycles=max_eval_cycles,
            cfg=cfg,
            client=client,
            train_seeds=train_seeds,
        )

    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    seeds = train_seeds or list(exp.get("eval", {}).get("train_seeds", list(range(8))))
    run_id = _uid("evo")

    seed_sel = int(run_id.replace("evo_", "")[:8], 16) % (2**31) if len(run_id) > 4 else 0
    sel0 = select_and_resolve(
        artifacts_dir,
        store,
        exp,
        policy=cfg.select,
        tournament_k=cfg.tournament_k,
        seed=seed_sel,
    )
    parent_dir = Path(sel0.path)
    parent_id = sel0.genome_id
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

    from organism.config import ROOT, nim_config
    from organism.manifest import build_manifest, write_manifest

    try:
        pins = nim_config().get("models", {})
    except Exception:
        pins = {}
    man = build_manifest(
        run_id=run_id,
        run_kind="evolve",
        root=ROOT,
        exp=exp,
        world={"grid": [world.height, world.width], "T": world.T},
        fitness={
            "epsilon_accept": fit.epsilon_accept,
            "delta_success": fit.delta_success,
            "lambda_std": fit.lambda_std,
        },
        weights={"alpha": wcfg.alpha, "init_std": wcfg.init_std},
        nim_pins={str(k): str(v) for k, v in pins.items()},
        rng_roots={"train_seeds": seeds},
        extra={
            "ablation": cfg.ablation,
            "dry_run": cfg.dry_run,
            "max_eval_cycles": max_eval_cycles,
            "max_mutations": cfg.max_mutations,
            "select": cfg.select,
            "tournament_k": cfg.tournament_k,
            "selection": sel0.to_dict(),
        },
    )
    man_path = write_manifest(artifacts_dir / "evolve" / f"{run_id}_manifest.json", man)

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
            "select": cfg.select,
            "selection": sel0.to_dict(),
            "manifest_path": str(man_path),
        },
    )
    events.append(
        asdict(
            EvolveEvent(
                kind="select",
                episode_index=0,
                fitness=sel0.fitness,
                genome_id=parent_id,
                reason=f"{sel0.policy}: {sel0.reason}",
            )
        )
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

        # Re-select parent for population dynamics (elites / rank / tournament)
        if (cfg.select or "active").lower() != "active":
            sel = select_and_resolve(
                artifacts_dir,
                store,
                exp,
                policy=cfg.select,
                tournament_k=cfg.tournament_k,
                seed=(seed_sel + mut_attempted) % (2**31),
            )
            parent_dir = Path(sel.path)
            parent_id = sel.genome_id
            events.append(
                asdict(
                    EvolveEvent(
                        kind="select",
                        episode_index=episodes_run,
                        fitness=sel.fitness,
                        genome_id=parent_id,
                        reason=f"{sel.policy}: {sel.reason}",
                    )
                )
            )
            store.log_event(
                "evolve_select",
                {"run_id": run_id, "mutation_n": mut_attempted, **sel.to_dict()},
            )

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
            if cfg.auto_elite_on_accept:
                try:
                    from organism.elites import promote_elite

                    promote_elite(
                        artifacts_dir,
                        store,
                        parent_id,
                        note=f"auto evolve accept {run_id}",
                        fitness=mres.candidate_fitness,
                    )
                except Exception:
                    pass
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
        max_lineages=1,
        lineage_schedule=cfg.lineage_schedule,
        lineages=[],
        budgets=cfg.budget_config().to_dict(),
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


def run_evolve_population(
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
    Multi-lineage evolve: up to max_lineages concurrent slots, scheduled by
    round_robin or fitness_rank, with per-lineage and global budgets.
    """
    from organism.config import ROOT, nim_config
    from organism.manifest import build_manifest, write_manifest
    from organism.sandbox import SandboxConfig

    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    seeds = train_seeds or list(exp.get("eval", {}).get("train_seeds", list(range(8))))
    run_id = _uid("evo")
    budgets = cfg.budget_config()
    seed_sel = int(run_id.replace("evo_", "")[:8], 16) % (2**31) if len(run_id) > 4 else 0

    slots = open_lineage_slots(
        artifacts_dir, store, exp, budgets, seed=seed_sel
    )
    for s in slots:
        store.insert_genome(
            genome_id=s.genome_id,
            status="active",
            ablation=cfg.ablation,
            artifact_path=s.path,
        )

    events: list[dict[str, Any]] = []
    episodes_run = 0
    eval_cycles = 0
    mut_attempted = mut_accepted = mut_rejected = mut_failed = 0
    fitness_history: list[float] = []
    rr_index = 0

    try:
        pins = nim_config().get("models", {})
    except Exception:
        pins = {}
    man = build_manifest(
        run_id=run_id,
        run_kind="evolve_population",
        root=ROOT,
        exp=exp,
        world={"grid": [world.height, world.width], "T": world.T},
        fitness={
            "epsilon_accept": fit.epsilon_accept,
            "delta_success": fit.delta_success,
            "lambda_std": fit.lambda_std,
        },
        weights={"alpha": wcfg.alpha, "init_std": wcfg.init_std},
        nim_pins={str(k): str(v) for k, v in pins.items()},
        rng_roots={"train_seeds": seeds},
        extra={
            "ablation": cfg.ablation,
            "dry_run": cfg.dry_run,
            "max_eval_cycles": max_eval_cycles,
            "max_mutations": cfg.max_mutations,
            "select": cfg.select,
            "budgets": budgets.to_dict(),
            "lineages": [s.to_dict() for s in slots],
        },
    )
    man_path = write_manifest(artifacts_dir / "evolve" / f"{run_id}_manifest.json", man)
    store.log_event(
        "evolve_population_start",
        {
            "run_id": run_id,
            "n_lineages": len(slots),
            "budgets": budgets.to_dict(),
            "manifest_path": str(man_path),
            "slots": [s.to_dict() for s in slots],
        },
    )
    events.append(
        asdict(
            EvolveEvent(
                kind="population_open",
                episode_index=0,
                reason=f"slots={len(slots)} schedule={budgets.schedule}",
                genome_id=slots[0].genome_id if slots else None,
            )
        )
    )

    start_id = slots[0].genome_id if slots else "none"
    sb = SandboxConfig.from_exp(exp)

    while eval_cycles < max_eval_cycles:
        ok_ep, ep_why = global_episodes_ok(episodes_run, budgets)
        if not ok_ep:
            events.append(
                asdict(
                    EvolveEvent(
                        kind="budget_stop",
                        episode_index=episodes_run,
                        reason=ep_why,
                    )
                )
            )
            break

        slot, rr_index, pick_why = pick_lineage(
            slots, budgets, rr_index=rr_index
        )
        if slot is None:
            events.append(
                asdict(
                    EvolveEvent(
                        kind="budget_stop",
                        episode_index=episodes_run,
                        reason=pick_why,
                    )
                )
            )
            break

        parent_dir = Path(slot.path)
        parent_id = slot.genome_id

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
        slot.fitness = result.fitness
        slot.fitness_history.append(result.fitness)
        slot.eval_cycles += 1
        slot.episodes_run += len(seeds)
        slot.episodes_since_mut += len(seeds)
        fitness_history.append(result.fitness)
        eval_cycles += 1
        episodes_run += len(seeds)

        events.append(
            asdict(
                EvolveEvent(
                    kind="eval",
                    episode_index=episodes_run,
                    fitness=result.fitness,
                    genome_id=parent_id,
                    reason=f"slot={slot.slot_id} {pick_why} cycle={slot.eval_cycles}",
                )
            )
        )

        # mark exhausted if hit per-lineage eval cap
        ok_e, why_e = lineage_can_eval(slot, budgets)
        if not ok_e:
            slot.exhausted = True
            slot.exhaust_reason = why_e

        if mut_attempted >= cfg.max_mutations:
            continue

        can_mut, mut_why = lineage_can_mutate(slot, budgets)
        if not can_mut:
            continue

        fire, reason = detect_trigger(
            episodes_since_mutation=slot.episodes_since_mut,
            fitness_history=slot.fitness_history,
            cfg=cfg,
        )
        if not fire:
            continue

        mut_attempted += 1
        slot.mutations_attempted += 1

        # Optional re-select parent into this slot from global pool
        if (cfg.select or "active").lower() != "active":
            sel = select_and_resolve(
                artifacts_dir,
                store,
                exp,
                policy=cfg.select,
                tournament_k=cfg.tournament_k,
                seed=(seed_sel + mut_attempted) % (2**31),
            )
            slot.genome_id = sel.genome_id
            slot.path = sel.path
            slot.fitness = sel.fitness
            parent_dir = Path(sel.path)
            parent_id = sel.genome_id
            events.append(
                asdict(
                    EvolveEvent(
                        kind="select",
                        episode_index=episodes_run,
                        fitness=sel.fitness,
                        genome_id=parent_id,
                        reason=f"slot={slot.slot_id} {sel.policy}: {sel.reason}",
                    )
                )
            )

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
        slot.episodes_since_mut = 0

        if mres.decision == "accepted":
            mut_accepted += 1
            slot.mutations_accepted += 1
            slot.path = str(mres.candidate_path)
            slot.genome_id = mres.candidate_genome_id
            if mres.candidate_fitness is not None:
                slot.fitness = mres.candidate_fitness
            if cfg.auto_elite_on_accept:
                try:
                    from organism.elites import promote_elite

                    promote_elite(
                        artifacts_dir,
                        store,
                        slot.genome_id,
                        note=f"auto pop-evolve accept {run_id}",
                        fitness=mres.candidate_fitness,
                    )
                except Exception:
                    pass
        elif mres.decision == "rejected":
            mut_rejected += 1
            slot.mutations_rejected += 1
        else:
            mut_failed += 1
            slot.mutations_failed += 1

        events.append(
            asdict(
                EvolveEvent(
                    kind=f"mutate_{reason}",
                    episode_index=episodes_run,
                    fitness=mres.candidate_fitness,
                    mutation_id=mres.mutation_id,
                    decision=mres.decision,
                    reason=f"slot={slot.slot_id} {mres.reason}",
                    genome_id=slot.genome_id,
                )
            )
        )

        can_mut2, mut_why2 = lineage_can_mutate(slot, budgets)
        if not can_mut2:
            slot.exhausted = True
            slot.exhaust_reason = mut_why2

    # Best lineage by last fitness
    best = max(
        slots,
        key=lambda s: (
            s.fitness is not None,
            float(s.fitness) if s.fitness is not None else float("-inf"),
        ),
    ) if slots else None

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
        final_genome_id=best.genome_id if best else start_id,
        final_genome_path=best.path if best else "",
        fitness_history=fitness_history,
        events=events,
        created_at=time.time(),
        max_lineages=budgets.max_lineages,
        lineage_schedule=budgets.schedule,
        lineages=[s.to_dict() for s in slots],
        budgets=budgets.to_dict(),
    )

    out_dir = artifacts_dir / "evolve"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{run_id}.json"
    out_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    (artifacts_dir / "last_evolve_report.json").write_text(
        json.dumps(report.to_dict(), indent=2), encoding="utf-8"
    )
    store.log_event(
        "evolve_population_end",
        {
            "run_id": run_id,
            "mutations_accepted": mut_accepted,
            "mutations_attempted": mut_attempted,
            "final_genome_id": report.final_genome_id,
            "n_lineages": len(slots),
            "report_path": str(out_path),
        },
    )
    return report
