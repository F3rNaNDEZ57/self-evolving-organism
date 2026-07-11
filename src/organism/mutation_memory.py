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
            "low_value",
        )
    ):
        hints.append(
            "Do NOT re-tweak nearest_food_direction / food-distance heuristics "
            "(repeated low_value). Try energy management, rest/forage timing, "
            "wall avoidance, or timeout survival instead."
        )
    if "energy" in blob and "low_value" in blob:
        hints.append(
            "Prior energy tweaks were rejected — if touching energy, make a "
            "clearly different rule (threshold or action switch), not a micro-edit."
        )
    if not hints:
        hints.append(
            "Propose a *different failure mode* than the rejects above "
            "(energy / walls / timeout / forage timing) — not the same function again."
        )
    return hints


def format_lessons_for_prompt(lessons: list[dict[str, Any]]) -> str:
    if not lessons:
        return ""
    lines = [
        "Past mutation lessons (do not repeat these mistakes; follow accepts):",
        "Observation fields ONLY: tick, energy, energy_max, x, y, local_food, vision, last_reward, alive.",
        "Policy.__init__(use_weights=False, weight_cfg=None, explore=0.1, train=False).",
        "random.choice(seq) has NO weights= keyword.",
    ]
    for h in _theme_hints(lessons):
        lines.append(f"DIVERSITY: {h}")
    for i, L in enumerate(lessons, 1):
        lines.append(
            f"{i}. [{L.get('decision')}] critic={L.get('critic_code') or '-'} "
            f"| {(L.get('reason') or '')[:120]}"
        )
        if L.get("rationale"):
            lines.append(f"   was: {L['rationale'][:100]}")
    return "\n".join(lines)
