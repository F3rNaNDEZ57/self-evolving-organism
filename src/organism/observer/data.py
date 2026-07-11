"""Read-only queries over SQLite + artifacts for the observer UI."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from organism.persistence import Store


def open_store(db_path: Path) -> Store:
    return Store(db_path)


def list_genomes(store: Store, limit: int = 200) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        """
        SELECT g.*,
          (SELECT fitness FROM evaluations e
           WHERE e.genome_id = g.id ORDER BY e.created_at DESC LIMIT 1) AS last_fitness
        FROM genomes g
        ORDER BY g.created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def list_mutations(store: Store, limit: int = 100) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        "SELECT * FROM mutations ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["meta"] = json.loads(d.get("meta_json") or "{}")
        except json.JSONDecodeError:
            d["meta"] = {}
        out.append(d)
    return out


def get_mutation(store: Store, mutation_id: str) -> dict[str, Any] | None:
    row = store.conn.execute(
        "SELECT * FROM mutations WHERE id=?", (mutation_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d["meta"] = json.loads(d.get("meta_json") or "{}")
    except json.JSONDecodeError:
        d["meta"] = {}
    d["llm"] = store.llm_usage_for_mutation(mutation_id)
    return d


def list_events(store: Store, limit: int = 150) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        "SELECT * FROM events ORDER BY ts DESC LIMIT ?",
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.get("payload_json") or "{}")
        except json.JSONDecodeError:
            d["payload"] = {}
        out.append(d)
    return out


def list_evaluations(store: Store, limit: int = 100) -> list[dict[str, Any]]:
    rows = store.conn.execute(
        "SELECT * FROM evaluations ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def lineage_edges(store: Store, limit: int = 300) -> list[tuple[str, str]]:
    """(parent_id, child_id) edges from genomes + mutations."""
    edges: list[tuple[str, str]] = []
    rows = store.conn.execute(
        """
        SELECT id, parent_id FROM genomes
        WHERE parent_id IS NOT NULL AND parent_id != ''
        ORDER BY created_at DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    for r in rows:
        edges.append((str(r["parent_id"]), str(r["id"])))
    # also mutation edges
    muts = store.conn.execute(
        """
        SELECT parent_genome_id, candidate_genome_id FROM mutations
        ORDER BY created_at DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    seen = set(edges)
    for r in muts:
        e = (str(r["parent_genome_id"]), str(r["candidate_genome_id"]))
        if e not in seen and e[0] and e[1]:
            edges.append(e)
            seen.add(e)
    return edges


def active_genome_info(artifacts_dir: Path) -> dict[str, Any] | None:
    p = Path(artifacts_dir) / "active_genome.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_json_artifact(artifacts_dir: Path, name: str) -> dict[str, Any] | None:
    p = Path(artifacts_dir) / name
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"_raw": data}
    except Exception:
        return None


def genome_sources(artifact_path: str | None, max_chars: int = 12000) -> dict[str, str]:
    """Load whitelist sources from a genome directory for inspector."""
    if not artifact_path:
        return {}
    d = Path(artifact_path)
    if not d.is_dir():
        # rejected sources folder or file
        if d.is_file():
            return {d.name: d.read_text(encoding="utf-8", errors="replace")[:max_chars]}
        return {}
    out: dict[str, str] = {}
    for name in ("policy.py", "heuristics.py", "memory_hooks.py"):
        fp = d / name
        if fp.exists():
            out[name] = fp.read_text(encoding="utf-8", errors="replace")[:max_chars]
    return out


def fmt_ts(ts: float | None) -> str:
    if not ts:
        return "—"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except Exception:
        return str(ts)


def pool_summary(store: Store) -> dict[str, Any]:
    from organism.metrics import collect_pool_metrics

    return collect_pool_metrics(store).to_dict()
