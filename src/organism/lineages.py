"""
Phase 5 multi-lineage budgets: concurrent lineage slots + spend limits.

Not the organism brain — operator-side resource accounting for evolve.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from organism.persistence import Store
from organism.selection import Candidate, gather_candidates

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
    content_key: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _path_ok(path: str | Path) -> bool:
    p = Path(path)
    if not (p.exists() and (p / "policy.py").exists()):
        return False
    # Skip broken/incomplete genomes so multi-lineage does not waste cycles
    try:
        from organism.validate import validate_genome_dir

        return not validate_genome_dir(p)
    except Exception:
        return True


def genome_content_key(path: str | Path) -> str:
    """
    Hash whitelist sources so clone genomes with identical code collapse
    into one content class for diversity-aware slot fill.
    """
    p = Path(path)
    h = hashlib.sha256()
    for name in ("heuristics.py", "policy.py", "memory_hooks.py"):
        fp = p / name
        if fp.exists():
            try:
                h.update(name.encode("utf-8"))
                h.update(fp.read_bytes())
            except OSError:
                continue
    return h.hexdigest()[:20]


def _seed_candidate(exp: dict[str, Any], store: Store | None) -> Candidate | None:
    """Optional seed genome as exploration parent (often different code)."""
    from organism.config import resolve_path

    seed_rel = (exp.get("paths") or {}).get("seed_genome", "genomes/seed")
    try:
        seed_path = resolve_path(seed_rel)
    except Exception:
        seed_path = Path(str(seed_rel))
    if not _path_ok(seed_path):
        return None
    fit = None
    if store is not None:
        try:
            row = store.conn.execute(
                "SELECT fitness FROM evaluations WHERE genome_id=? "
                "ORDER BY created_at DESC LIMIT 1",
                ("g_seed",),
            ).fetchone()
            if row is not None and row["fitness"] is not None:
                fit = float(row["fitness"])
        except Exception:
            fit = None
    return Candidate(
        genome_id="g_seed",
        path=str(seed_path),
        fitness=fit,
        source="seed",
    )


def open_lineage_slots(
    artifacts_dir: Path,
    store: Store | None,
    exp: dict[str, Any],
    budgets: BudgetConfig,
    *,
    seed: int = 0,
) -> list[LineageSlot]:
    """
    Seed up to max_lineages slots with **content-diverse** parents.

    Prefer higher fitness, but skip genomes whose whitelist code hash already
    filled a slot. Always try to include seed as an exploration arm when under
    filled. Does not clone the champion into empty slots.
    """
    n = max(1, int(budgets.max_lineages))
    cands = gather_candidates(
        artifacts_dir,
        store,
        exp,
        include_active=True,
        include_elites=True,
        include_db=True,
        db_limit=80,
    )
    seed_c = _seed_candidate(exp, store)
    if seed_c is not None:
        cands = list(cands) + [seed_c]

    # unique by genome_id, path must resolve
    by_id: dict[str, Candidate] = {}
    for c in cands:
        if c.genome_id in by_id:
            continue
        if not _path_ok(c.path):
            continue
        by_id[c.genome_id] = c

    source_rank = {"active": 0, "elite": 1, "db": 2, "seed": 3}

    def _rank_key(c: Candidate) -> tuple:
        fit = float(c.fitness) if c.fitness is not None else float("-inf")
        # higher fitness first; then prefer active/elite over seed/db
        return (c.fitness is not None, fit, -source_rank.get(c.source, 9))

    ordered = sorted(by_id.values(), key=_rank_key, reverse=True)

    slots: list[LineageSlot] = []
    seen_content: set[str] = set()

    def _try_add(c: Candidate) -> bool:
        if len(slots) >= n:
            return False
        key = genome_content_key(c.path)
        if key in seen_content:
            return False
        seen_content.add(key)
        slots.append(
            LineageSlot(
                slot_id=len(slots),
                genome_id=c.genome_id,
                path=c.path,
                fitness=c.fitness,
                content_key=key,
                source=c.source,
            )
        )
        return True

    # Pass 1: fitness-ordered unique content
    for c in ordered:
        _try_add(c)
        if len(slots) >= n:
            break

    # Pass 2: force seed exploration arm if still room and not already present
    if len(slots) < n and seed_c is not None and _path_ok(seed_c.path):
        if seed_c.genome_id not in {s.genome_id for s in slots}:
            _try_add(seed_c)

    # Pass 3: remaining unique content regardless of fitness order gaps
    if len(slots) < n:
        for c in ordered:
            if c.genome_id in {s.genome_id for s in slots}:
                continue
            _try_add(c)
            if len(slots) >= n:
                break

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
                content_key=genome_content_key(sel.path),
                source="active",
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
