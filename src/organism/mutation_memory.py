"""Structured mutation memory for coder/critic prompts (no vector DB)."""

from __future__ import annotations

import json
from typing import Any

from organism.persistence import Store


def retrieve_mutation_lessons(
    store: Store,
    *,
    k: int = 5,
    parent_genome_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Pull recent accept/reject/fail lessons from SQLite for prompt injection.
    Prefers same parent lineage, then global recent.
    """
    lessons: list[dict[str, Any]] = []
    rows: list[Any] = []
    if parent_genome_id:
        rows = store.conn.execute(
            """
            SELECT id, decision, reason, meta_json, created_at
            FROM mutations
            WHERE parent_genome_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (parent_genome_id, k * 2),
        ).fetchall()
    if len(rows) < k:
        rows = store.conn.execute(
            """
            SELECT id, decision, reason, meta_json, created_at
            FROM mutations
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (k * 3,),
        ).fetchall()

    for r in rows:
        try:
            meta = json.loads(r["meta_json"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        critic = meta.get("critic") or {}
        lesson = {
            "mutation_id": r["id"],
            "decision": r["decision"],
            "reason": (r["reason"] or "")[:200],
            "critic_code": critic.get("code") or "",
            "rationale": str(meta.get("rationale") or "")[:160],
            "parent_fitness": meta.get("parent_fitness"),
            "candidate_fitness": meta.get("candidate_fitness"),
        }
        # Prefer failures that teach something
        if r["decision"] in ("failed", "rejected") or r["decision"] == "accepted":
            lessons.append(lesson)
        if len(lessons) >= k:
            break
    return lessons[:k]


def format_lessons_for_prompt(lessons: list[dict[str, Any]]) -> str:
    if not lessons:
        return ""
    lines = [
        "Past mutation lessons (do not repeat these mistakes; follow accepts):",
        "Observation fields ONLY: tick, energy, energy_max, x, y, local_food, vision, last_reward, alive.",
        "Policy.__init__(use_weights=False, weight_cfg=None, explore=0.1, train=False).",
        "random.choice(seq) has NO weights= keyword.",
    ]
    for i, L in enumerate(lessons, 1):
        lines.append(
            f"{i}. [{L.get('decision')}] critic={L.get('critic_code') or '-'} "
            f"| {(L.get('reason') or '')[:120]}"
        )
        if L.get("rationale"):
            lines.append(f"   was: {L['rationale'][:100]}")
    return "\n".join(lines)
