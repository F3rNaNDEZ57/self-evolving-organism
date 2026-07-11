"""
Phase 5 parent selection: active | fitness_rank | tournament.

Operator / evolve loop picks a mutation parent from elites (+ active / DB).
Does not change fitness math — selection only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from organism.elites import list_elites, resolve_genome_dir
from organism.mutation import resolve_parent_genome
from organism.persistence import Store

SelectPolicy = Literal["active", "fitness_rank", "tournament"]
SELECT_POLICIES: tuple[str, ...] = ("active", "fitness_rank", "tournament")


@dataclass
class Candidate:
    genome_id: str
    path: str
    fitness: float | None
    source: str  # elite | active | db

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SelectionResult:
    genome_id: str
    path: str
    fitness: float | None
    policy: str
    reason: str
    pool_size: int = 0
    tournament_k: int = 0
    shortlist: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _last_fitness(store: Store | None, genome_id: str) -> float | None:
    if store is None:
        return None
    try:
        row = store.conn.execute(
            "SELECT fitness FROM evaluations WHERE genome_id=? ORDER BY created_at DESC LIMIT 1",
            (genome_id,),
        ).fetchone()
        if row is not None and row["fitness"] is not None:
            return float(row["fitness"])
    except Exception:
        return None
    return None


def gather_candidates(
    artifacts_dir: Path,
    store: Store | None,
    exp: dict[str, Any] | None = None,
    *,
    include_active: bool = True,
    include_elites: bool = True,
    include_db: bool = True,
    db_limit: int = 30,
) -> list[Candidate]:
    """Build selection pool with resolvable policy.py paths."""
    artifacts_dir = Path(artifacts_dir)
    seen: set[str] = set()
    out: list[Candidate] = []

    def _add(gid: str, path: Path, fitness: float | None, source: str) -> None:
        gid = str(gid)
        if not gid or gid in seen:
            return
        if not path.exists() or not (path / "policy.py").exists():
            return
        seen.add(gid)
        if fitness is None:
            fitness = _last_fitness(store, gid)
        out.append(
            Candidate(
                genome_id=gid,
                path=str(path),
                fitness=fitness,
                source=source,
            )
        )

    if include_elites:
        for e in list_elites(artifacts_dir):
            gid = str(e.get("genome_id") or "")
            p = Path(str(e.get("path") or ""))
            fit = e.get("fitness")
            fit_f = float(fit) if isinstance(fit, (int, float)) else None
            _add(gid, p, fit_f, "elite")

    if include_active and exp is not None:
        try:
            path, gid = resolve_parent_genome(exp, parent_id="", store=store)
            _add(gid, path, None, "active")
        except Exception:
            pass

    if include_db and store is not None:
        try:
            rows = store.conn.execute(
                """
                SELECT g.id, g.artifact_path,
                  (SELECT fitness FROM evaluations e
                   WHERE e.genome_id = g.id ORDER BY e.created_at DESC LIMIT 1) AS last_fitness
                FROM genomes g
                ORDER BY g.created_at DESC
                LIMIT ?
                """,
                (int(db_limit),),
            ).fetchall()
            for r in rows:
                gid = str(r["id"])
                p = Path(str(r["artifact_path"] or ""))
                fit = r["last_fitness"]
                fit_f = float(fit) if fit is not None else None
                _add(gid, p, fit_f, "db")
        except Exception:
            pass

    return out


def _ranked(cands: list[Candidate]) -> list[Candidate]:
    """Sort by fitness desc; missing fitness sorts last."""
    return sorted(
        cands,
        key=lambda c: (
            c.fitness is not None,
            float(c.fitness) if c.fitness is not None else float("-inf"),
        ),
        reverse=True,
    )


def select_parent(
    artifacts_dir: Path,
    store: Store | None,
    exp: dict[str, Any],
    *,
    policy: str = "active",
    tournament_k: int = 3,
    rng: np.random.Generator | None = None,
    seed: int | None = None,
) -> SelectionResult:
    """
    Choose mutation parent.

    - active: current active_genome / seed
    - fitness_rank: highest last fitness among elites (+ active + recent DB)
    - tournament: sample k from pool, pick best fitness among shortlist
    """
    artifacts_dir = Path(artifacts_dir)
    pol = (policy or "active").strip().lower()
    if pol not in SELECT_POLICIES:
        pol = "active"

    if pol == "active":
        path, gid = resolve_parent_genome(exp, parent_id="", store=store)
        fit = _last_fitness(store, gid)
        return SelectionResult(
            genome_id=gid,
            path=str(path),
            fitness=fit,
            policy="active",
            reason="active_genome_pointer",
            pool_size=1,
        )

    cands = gather_candidates(
        artifacts_dir,
        store,
        exp,
        include_active=True,
        include_elites=True,
        include_db=True,
    )
    if not cands:
        path, gid = resolve_parent_genome(exp, parent_id="", store=store)
        return SelectionResult(
            genome_id=gid,
            path=str(path),
            fitness=_last_fitness(store, gid),
            policy=pol,
            reason="fallback_active_empty_pool",
            pool_size=0,
        )

    # Prefer candidates that have a fitness score when ranking
    scored = [c for c in cands if c.fitness is not None]
    pool = scored if scored else cands
    rng = rng or np.random.default_rng(seed)

    if pol == "fitness_rank":
        ranked = _ranked(pool)
        best = ranked[0]
        return SelectionResult(
            genome_id=best.genome_id,
            path=best.path,
            fitness=best.fitness,
            policy="fitness_rank",
            reason=(
                f"best_fitness={best.fitness:.4f} source={best.source}"
                if best.fitness is not None
                else f"unscored_pool source={best.source}"
            ),
            pool_size=len(pool),
            shortlist=[c.to_dict() for c in ranked[:5]],
        )

    # tournament
    k = max(1, min(int(tournament_k), len(pool)))
    idxs = rng.choice(len(pool), size=k, replace=False)
    shortlist = [pool[int(i)] for i in idxs]
    winner = _ranked(shortlist)[0]
    return SelectionResult(
        genome_id=winner.genome_id,
        path=winner.path,
        fitness=winner.fitness,
        policy="tournament",
        reason=(
            f"tournament_k={k} winner={winner.genome_id} "
            f"fit={winner.fitness if winner.fitness is not None else 'n/a'} "
            f"source={winner.source}"
        ),
        pool_size=len(pool),
        tournament_k=k,
        shortlist=[c.to_dict() for c in shortlist],
    )


def select_and_resolve(
    artifacts_dir: Path,
    store: Store | None,
    exp: dict[str, Any],
    *,
    policy: str = "active",
    tournament_k: int = 3,
    parent_id: str = "",
    seed: int | None = None,
) -> SelectionResult:
    """
    If parent_id set → explicit parent (manual).
    Else apply policy.
    """
    artifacts_dir = Path(artifacts_dir)
    if (parent_id or "").strip():
        path, gid = resolve_genome_dir(artifacts_dir, parent_id.strip(), store=store)
        return SelectionResult(
            genome_id=gid,
            path=str(path),
            fitness=_last_fitness(store, gid),
            policy="explicit",
            reason=f"operator_parent_id={gid}",
            pool_size=1,
        )
    return select_parent(
        artifacts_dir,
        store,
        exp,
        policy=policy,
        tournament_k=tournament_k,
        seed=seed,
    )
