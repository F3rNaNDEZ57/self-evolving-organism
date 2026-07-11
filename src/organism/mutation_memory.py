"""Structured mutation memory for coder/critic prompts (no vector DB).

Gives the free-NIM coder a compact **self-improvement history**:
accepts to copy, rejects to avoid, fitness deltas, and diversity themes.
"""

from __future__ import annotations

import json
from typing import Any

from organism.persistence import Store


def retrieve_mutation_lessons(
    store: Store,
    *,
    k: int = 10,
    parent_genome_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Pull recent accept/reject/fail lessons from SQLite for prompt injection.

    Strategy:
    1. Recent accepts (what worked) — up to k//3
    2. Same-parent rejects/fails (lineage memory)
    3. Global recent rejects (avoid repeating global dead ends)
    """
    k = max(3, int(k))
    seen: set[str] = set()
    lessons: list[dict[str, Any]] = []

    def _rows(sql: str, params: tuple[Any, ...]) -> list[Any]:
        try:
            return list(store.conn.execute(sql, params).fetchall())
        except Exception:
            return []

    def _add_rows(rows: list[Any], *, limit: int) -> None:
        for r in rows:
            mid = str(r["id"])
            if mid in seen:
                continue
            try:
                meta = json.loads(r["meta_json"] or "{}")
            except json.JSONDecodeError:
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
            critic = meta.get("critic") or {}
            if not isinstance(critic, dict):
                critic = {}
            pf = meta.get("parent_fitness")
            cf = meta.get("candidate_fitness")
            delta = None
            try:
                if pf is not None and cf is not None:
                    delta = float(cf) - float(pf)
            except Exception:
                delta = None
            files = meta.get("files_changed") or meta.get("files") or []
            if isinstance(files, dict):
                files = list(files.keys())
            def _rg(key: str, default: Any = None) -> Any:
                try:
                    return r[key]
                except (KeyError, IndexError, TypeError):
                    return default

            lesson = {
                "mutation_id": mid,
                "decision": r["decision"],
                "reason": (r["reason"] or "")[:220],
                "critic_code": critic.get("code") or meta.get("quality_gate") or "",
                "rationale": str(meta.get("rationale") or "")[:180],
                "parent_fitness": pf,
                "candidate_fitness": cf,
                "delta": delta,
                "files_changed": list(files)[:6] if isinstance(files, list) else [],
                "parent_genome_id": _rg("parent_genome_id", meta.get("parent_genome_id")),
                "candidate_genome_id": _rg("candidate_genome_id"),
            }
            if r["decision"] in ("failed", "rejected", "accepted"):
                seen.add(mid)
                lessons.append(lesson)
            if len(lessons) >= limit:
                return

    # 1) Global accepts first (positive examples)
    n_acc = max(1, k // 3)
    acc = _rows(
        """
        SELECT id, parent_genome_id, candidate_genome_id, decision, reason, meta_json, created_at
        FROM mutations WHERE decision = 'accepted'
        ORDER BY created_at DESC LIMIT ?
        """,
        (n_acc * 2,),
    )
    _add_rows(acc, limit=n_acc)

    # 2) Same-parent history
    if parent_genome_id and len(lessons) < k:
        same = _rows(
            """
            SELECT id, parent_genome_id, candidate_genome_id, decision, reason, meta_json, created_at
            FROM mutations WHERE parent_genome_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (parent_genome_id, k * 2),
        )
        _add_rows(same, limit=k)

    # 3) Global recent
    if len(lessons) < k:
        glob = _rows(
            """
            SELECT id, parent_genome_id, candidate_genome_id, decision, reason, meta_json, created_at
            FROM mutations
            ORDER BY created_at DESC LIMIT ?
            """,
            (k * 3,),
        )
        _add_rows(glob, limit=k)

    return lessons[:k]


def _theme_hints(lessons: list[dict[str, Any]]) -> list[str]:
    """Detect repeated failure themes so the coder tries a different lever."""
    blob = " ".join(
        f"{L.get('reason') or ''} {L.get('rationale') or ''} {L.get('critic_code') or ''}"
        for L in lessons
    ).lower()
    hints: list[str] = []
    if any(
        k in blob
        for k in (
            "nearest_food",
            "food selection",
            "food_direction",
            "should_forage",
            "low_value",
        )
    ):
        hints.append(
            "Do NOT re-tweak nearest_food_direction / should_forage / food-distance "
            "(repeated low_value). Prefer energy drain, rest-vs-move, or survival timing "
            "using only allowed Observation fields."
        )
    if "local_walls" in blob or "position" in blob or "contract_break" in blob:
        hints.append(
            "Do NOT invent Observation fields (no position, local_walls, health, grid). "
            "ONLY: tick, energy, energy_max, x, y, local_food, vision, last_reward, alive."
        )
    if "energy" in blob and ("low_value" in blob or "fitness" in blob):
        hints.append(
            "Prior energy attempts failed fitness or critic — if changing energy logic, "
            "use a clear threshold/action switch with measurable survival impact."
        )
    if "nonsense" in blob or "no mutation code" in blob or "empty" in blob or "quality gate" in blob:
        hints.append(
            "Previous replies had empty/missing file bodies. Return COMPLETE "
            "heuristics.py source inside JSON files — never prose-only or no-op clones."
        )
    if not hints:
        hints.append(
            "Propose a *different failure mode* than the rejects above "
            "(energy / rest / timeout survival) — not the same function again."
        )
    return hints


def format_lessons_for_prompt(lessons: list[dict[str, Any]]) -> str:
    """Render lessons as a self-improvement brief for the mutation coder."""
    if not lessons:
        return (
            "Mutation history: (none yet). Make a small, complete heuristics.py change "
            "aimed at energy/rest survival. Full file body required.\n"
            "Observation fields ONLY: tick, energy, energy_max, x, y, local_food, vision, last_reward, alive.\n"
        )
    accepts = [L for L in lessons if L.get("decision") == "accepted"]
    rejects = [L for L in lessons if L.get("decision") != "accepted"]

    lines = [
        "=== MUTATION SELF-IMPROVEMENT HISTORY (use this; do not repeat failures) ===",
        "Observation fields ONLY: tick, energy, energy_max, x, y, local_food, vision, last_reward, alive.",
        "Policy.__init__(use_weights=False, weight_cfg=None, explore=0.1, train=False).",
        "random.choice(seq) has NO weights= keyword.",
        "Goal: produce a COMPLETE JSON patch that can BEAT parent fitness (not cosmetic).",
    ]
    for h in _theme_hints(lessons):
        lines.append(f"DIVERSITY: {h}")

    if accepts:
        lines.append("")
        lines.append("--- What WORKED (copy patterns, not exact code) ---")
        for i, L in enumerate(accepts[:4], 1):
            dlt = L.get("delta")
            dlt_s = f"{float(dlt):+.3f}" if isinstance(dlt, (int, float)) else "?"
            lines.append(
                f"A{i}. [accepted] Δfit={dlt_s} "
                f"parent={L.get('parent_fitness')} → cand={L.get('candidate_fitness')} "
                f"files={L.get('files_changed') or '-'}"
            )
            if L.get("rationale"):
                lines.append(f"    why: {L['rationale'][:140]}")
            if L.get("reason"):
                lines.append(f"    gate: {(L.get('reason') or '')[:100]}")

    if rejects:
        lines.append("")
        lines.append("--- What FAILED (do not repeat) ---")
        for i, L in enumerate(rejects[:8], 1):
            dlt = L.get("delta")
            dlt_s = f"{float(dlt):+.3f}" if isinstance(dlt, (int, float)) else "?"
            lines.append(
                f"R{i}. [{L.get('decision')}] critic={L.get('critic_code') or '-'} "
                f"Δfit={dlt_s} | {(L.get('reason') or '')[:130]}"
            )
            if L.get("rationale"):
                lines.append(f"    was: {L['rationale'][:120]}")

    lines.append("")
    lines.append(
        "Your task: propose the NEXT step that learns from A* and R* above — "
        "one small FULL-file change (prefer heuristics.py) targeting energy/rest/timeout."
    )
    return "\n".join(lines)
