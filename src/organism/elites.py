"""
Phase 5 scaffold: elite archive (operator-curated genome pool).

Elites are references to existing genome artifacts — not a second brain.
Registry: artifacts/elites/registry.json
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from organism.persistence import Store


def elites_dir(artifacts_dir: Path) -> Path:
    d = Path(artifacts_dir) / "elites"
    d.mkdir(parents=True, exist_ok=True)
    return d


def registry_path(artifacts_dir: Path) -> Path:
    return elites_dir(artifacts_dir) / "registry.json"


def load_registry(artifacts_dir: Path) -> dict[str, Any]:
    p = registry_path(artifacts_dir)
    if not p.exists():
        return {"elites": [], "updated_at": 0.0}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"elites": [], "updated_at": 0.0}
        data.setdefault("elites", [])
        return data
    except Exception:
        return {"elites": [], "updated_at": 0.0}


def save_registry(artifacts_dir: Path, data: dict[str, Any]) -> Path:
    p = registry_path(artifacts_dir)
    data = dict(data)
    data["updated_at"] = time.time()
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return p


def list_elites(artifacts_dir: Path) -> list[dict[str, Any]]:
    """Return elite entries (newest first). Drops broken paths from the view only."""
    reg = load_registry(artifacts_dir)
    out: list[dict[str, Any]] = []
    for e in reg.get("elites") or []:
        if not isinstance(e, dict):
            continue
        path = str(e.get("path") or "")
        entry = dict(e)
        entry["path_ok"] = bool(path and Path(path).exists() and (Path(path) / "policy.py").exists())
        out.append(entry)
    out.sort(key=lambda x: float(x.get("promoted_at") or 0), reverse=True)
    return out


def is_elite(artifacts_dir: Path, genome_id: str) -> bool:
    gid = str(genome_id)
    return any(str(e.get("genome_id")) == gid for e in list_elites(artifacts_dir))


def promote_elite(
    artifacts_dir: Path,
    store: Store,
    genome_id: str,
    *,
    note: str = "",
    fitness: float | None = None,
) -> dict[str, Any]:
    """
    Add genome to elite archive. Idempotent if already elite (updates note/fitness).
    Does not change active_genome.json.
    """
    artifacts_dir = Path(artifacts_dir)
    gid = str(genome_id).strip()
    if not gid:
        raise ValueError("genome_id required")

    row = store.get_genome(gid)
    path = ""
    if row:
        path = str(row.get("artifact_path") or "")
    if not path or not Path(path).exists():
        # fall back to conventional artifact layout
        cand = artifacts_dir / "genomes" / gid
        if (cand / "policy.py").exists():
            path = str(cand)
    if not path or not (Path(path) / "policy.py").exists():
        raise FileNotFoundError(f"genome artifact not found for {gid}")

    if fitness is None and row:
        # best-effort last fitness from evaluations
        try:
            ev = store.conn.execute(
                "SELECT fitness FROM evaluations WHERE genome_id=? ORDER BY created_at DESC LIMIT 1",
                (gid,),
            ).fetchone()
            if ev is not None:
                fitness = float(ev["fitness"])
        except Exception:
            fitness = None

    reg = load_registry(artifacts_dir)
    elites: list[dict[str, Any]] = list(reg.get("elites") or [])
    now = time.time()
    found = False
    for e in elites:
        if str(e.get("genome_id")) == gid:
            e["path"] = path
            e["note"] = note or e.get("note") or ""
            if fitness is not None:
                e["fitness"] = fitness
            e["promoted_at"] = now
            found = True
            entry = e
            break
    if not found:
        entry = {
            "genome_id": gid,
            "path": path,
            "fitness": fitness,
            "note": note,
            "promoted_at": now,
            "parent_id": (row or {}).get("parent_id"),
            "ablation": (row or {}).get("ablation"),
        }
        elites.append(entry)

    reg["elites"] = elites
    save_registry(artifacts_dir, reg)

    # Soft tag in DB without demoting unique active pointer semantics
    try:
        cur = store.get_genome(gid)
        if cur and cur.get("status") not in ("active", "elite"):
            store.set_genome_status(gid, "elite")
        elif cur is None:
            store.insert_genome(
                genome_id=gid,
                parent_id=(row or {}).get("parent_id") if row else None,
                status="elite",
                ablation=str((row or {}).get("ablation") or "Bc"),
                artifact_path=path,
            )
        elif cur and cur.get("status") != "active":
            store.set_genome_status(gid, "elite")
    except Exception:
        pass

    store.log_event(
        "elite_promote",
        {"genome_id": gid, "path": path, "fitness": fitness, "note": note},
    )
    return entry


def demote_elite(artifacts_dir: Path, store: Store | None, genome_id: str) -> bool:
    """Remove from elite registry. Returns True if removed."""
    gid = str(genome_id).strip()
    reg = load_registry(artifacts_dir)
    before = len(reg.get("elites") or [])
    reg["elites"] = [e for e in (reg.get("elites") or []) if str(e.get("genome_id")) != gid]
    after = len(reg["elites"])
    if after == before:
        return False
    save_registry(artifacts_dir, reg)
    if store is not None:
        try:
            row = store.get_genome(gid)
            if row and row.get("status") == "elite":
                store.set_genome_status(gid, "archived")
            store.log_event("elite_demote", {"genome_id": gid})
        except Exception:
            pass
    return True


def resolve_genome_dir(
    artifacts_dir: Path,
    genome_id: str,
    store: Store | None = None,
) -> tuple[Path, str]:
    """Resolve genome_id → (dir with policy.py, id)."""
    artifacts_dir = Path(artifacts_dir)
    gid = str(genome_id).strip()
    if not gid:
        raise ValueError("genome_id required")

    # Elite registry first
    for e in list_elites(artifacts_dir):
        if str(e.get("genome_id")) == gid:
            p = Path(str(e.get("path") or ""))
            if p.exists() and (p / "policy.py").exists():
                return p, gid

    if store is not None:
        row = store.get_genome(gid)
        if row:
            p = Path(str(row.get("artifact_path") or ""))
            if p.exists() and (p / "policy.py").exists():
                return p, gid

    for cand in (
        artifacts_dir / "genomes" / gid,
        artifacts_dir / "genomes" / "active",
    ):
        if (cand / "policy.py").exists():
            return cand, gid

    raise FileNotFoundError(f"cannot resolve genome path for {gid}")
