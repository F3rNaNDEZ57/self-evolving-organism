"""
Phase 5 multi-lineage budgets: concurrent lineage slots + spend limits.

Not the organism brain — operator-side resource accounting for evolve.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from organism.persistence import Store
from organism.selection import gather_candidates

Schedule = Literal["round_robin", "fitness_rank"]


@dataclass
class BudgetConfig:
    """Resource caps for multi-lineage evolve."""

    max_lineages: int = 1
    # 0 = no per-lineage cap (use global only)
    max_eval_cycles_per_lineage: int = 0
    max_mutations_per_lineage: int = 0
    # optional extra global episode ceiling (seed-episodes); 0 = off
    max_episodes_total: int = 0
    schedule: str = "round_robin"  # round_robin | fitness_rank

    @classmethod
    def from_exp(cls, exp: dict[str, Any]) -> BudgetConfig:
        evo = exp.get("evolve", {}) or {}
        bud = evo.get("budgets", {}) or {}
        return cls(
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
            schedule=str(bud.get("schedule", evo.get("lineage_schedule", "round_robin"))),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LineageSlot:
    slot_id: int
    genome_id: str
    path: str
    fitness: float | None = None
    fitness_history: list[float] = field(default_factory=list)
    eval_cycles: int = 0
    episodes_run: int = 0
    episodes_since_mut: int = 0
    mutations_attempted: int = 0
    mutations_accepted: int = 0
    mutations_rejected: int = 0
    mutations_failed: int = 0
    exhausted: bool = False
    exhaust_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _path_ok(path: str | Path) -> bool:
    p = Path(path)
    return p.exists() and (p / "policy.py").exists()


def open_lineage_slots(
    artifacts_dir: Path,
    store: Store | None,
    exp: dict[str, Any],
    budgets: BudgetConfig,
    *,
    seed: int = 0,
) -> list[LineageSlot]:
    """
    Seed up to max_lineages slots from elites + active + recent DB.
    Prefer higher fitness first; fill uniquely.
    """
    n = max(1, int(budgets.max_lineages))
    cands = gather_candidates(
        artifacts_dir,
        store,
        exp,
        include_active=True,
        include_elites=True,
        include_db=True,
        db_limit=50,
    )
    # unique by genome_id, path must resolve
    by_id: dict[str, Any] = {}
    for c in cands:
        if c.genome_id in by_id:
            continue
        if not _path_ok(c.path):
            continue
        by_id[c.genome_id] = c

    ordered = sorted(
        by_id.values(),
        key=lambda c: (
            c.fitness is not None,
            float(c.fitness) if c.fitness is not None else float("-inf"),
        ),
        reverse=True,
    )

    slots: list[LineageSlot] = []
    for i, c in enumerate(ordered[:n]):
        slots.append(
            LineageSlot(
                slot_id=i,
                genome_id=c.genome_id,
                path=c.path,
                fitness=c.fitness,
            )
        )

    # If fewer candidates than max_lineages, duplicate best with same path
    # is wrong scientifically — just run with what we have.
    if not slots:
        # last resort: active via selection
        from organism.selection import select_and_resolve

        sel = select_and_resolve(
            artifacts_dir, store, exp, policy="active", seed=seed
        )
        slots.append(
            LineageSlot(
                slot_id=0,
                genome_id=sel.genome_id,
                path=sel.path,
                fitness=sel.fitness,
            )
        )
    return slots


def lineage_can_eval(slot: LineageSlot, budgets: BudgetConfig) -> tuple[bool, str]:
    if slot.exhausted:
        return False, slot.exhaust_reason or "exhausted"
    cap = int(budgets.max_eval_cycles_per_lineage or 0)
    if cap > 0 and slot.eval_cycles >= cap:
        return False, f"eval_cap={cap}"
    return True, ""


def lineage_can_mutate(slot: LineageSlot, budgets: BudgetConfig) -> tuple[bool, str]:
    if slot.exhausted:
        return False, slot.exhaust_reason or "exhausted"
    cap = int(budgets.max_mutations_per_lineage or 0)
    if cap > 0 and slot.mutations_attempted >= cap:
        return False, f"mut_cap={cap}"
    return True, ""


def pick_lineage(
    slots: list[LineageSlot],
    budgets: BudgetConfig,
    *,
    rr_index: int,
    rng: np.random.Generator | None = None,
) -> tuple[LineageSlot | None, int, str]:
    """
    Choose next lineage for an eval cycle.
    Returns (slot|None, new_rr_index, reason).
    """
    eligible = []
    for s in slots:
        ok, why = lineage_can_eval(s, budgets)
        if ok:
            eligible.append(s)
        else:
            s.exhausted = True
            s.exhaust_reason = why

    if not eligible:
        return None, rr_index, "no_eligible_lineages"

    sched = (budgets.schedule or "round_robin").strip().lower()
    if sched == "fitness_rank":
        ranked = sorted(
            eligible,
            key=lambda s: (
                s.fitness is not None,
                float(s.fitness) if s.fitness is not None else float("-inf"),
            ),
            reverse=True,
        )
        return ranked[0], rr_index, "schedule=fitness_rank"

    # round_robin among eligible
    if not eligible:
        return None, rr_index, "no_eligible_lineages"
    idx = int(rr_index) % len(eligible)
    chosen = eligible[idx]
    return chosen, rr_index + 1, f"schedule=round_robin i={idx}"


def global_episodes_ok(episodes_run: int, budgets: BudgetConfig) -> tuple[bool, str]:
    cap = int(budgets.max_episodes_total or 0)
    if cap > 0 and episodes_run >= cap:
        return False, f"global_episode_cap={cap}"
    return True, ""
