"""Experience distillation for mutation/critic context (free NIM summarizer)."""

from __future__ import annotations

import json
from typing import Any

from organism.nim_client import NimClient
from organism.router import FreeNimRouter

SUMMARIZE_SYSTEM = """You distill episode outcomes for a self-evolving grid organism.
Return ONLY JSON (no markdown):
{
  "bullets": ["short failure/success pattern", "..."],
  "failure_modes": ["energy|missed_food|thrashing|..."],
  "hints": ["one actionable code hint for policy/heuristics", "..."]
}
Max 5 bullets, 4 failure_modes, 3 hints. Be concrete and brief.
"""


def distill_episodes_offline(episode_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic distillation (dry-run / no NIM)."""
    if not episode_summaries:
        return {
            "bullets": ["no episode data"],
            "failure_modes": [],
            "hints": ["prefer food-seeking over random walk"],
            "dry_run": True,
        }
    foods = [int(e.get("food", e.get("food_collected", 0)) or 0) for e in episode_summaries]
    scores = [float(e.get("score", 0) or 0) for e in episode_summaries]
    deaths = [str(e.get("death", e.get("death_reason", "")) or "") for e in episode_summaries]
    mean_food = sum(foods) / max(1, len(foods))
    mean_score = sum(scores) / max(1, len(scores))
    energy_deaths = sum(1 for d in deaths if d == "energy")
    bullets = [
        f"n={len(episode_summaries)} episodes mean_food={mean_food:.2f} mean_score={mean_score:.2f}",
        f"energy_deaths={energy_deaths}/{len(deaths)}",
    ]
    if mean_food < 1:
        bullets.append("rarely collecting food - strengthen forage / chase")
    failure_modes = []
    if energy_deaths:
        failure_modes.append("energy")
    if mean_food < 0.5:
        failure_modes.append("missed_food")
    if any(s < 1 for s in scores):
        failure_modes.append("low_score")
    hints = []
    if mean_food < 1:
        hints.append("increase probability of moving toward nearest food")
    if energy_deaths > len(deaths) // 2:
        hints.append("rest or forage earlier when energy is low")
    if not hints:
        hints.append("keep changes small and survival-safe")
    return {
        "bullets": bullets[:5],
        "failure_modes": failure_modes[:4],
        "hints": hints[:3],
        "dry_run": True,
    }


def distill_episodes(
    episode_summaries: list[dict[str, Any]],
    *,
    client: NimClient | None = None,
    router: FreeNimRouter | None = None,
    dry_run: bool = False,
    store: Any | None = None,
    mutation_id: str | None = None,
) -> dict[str, Any]:
    """
    Distill recent episode summaries into short critic/coder context.
    Uses free summarizer pin when live; offline heuristic when dry_run.
    """
    if dry_run or (client is None and router is None):
        return distill_episodes_offline(episode_summaries)

    payload = {
        "episodes": (episode_summaries or [])[:8],
    }
    user = f"Distill these episode outcomes:\n{json.dumps(payload)}"
    try:
        if router is not None:
            chat = router.chat(
                "summarize",
                [
                    {"role": "system", "content": SUMMARIZE_SYSTEM},
                    {"role": "user", "content": user},
                ],
                max_tokens=400,
                temperature=0.1,
            )
        else:
            assert client is not None
            model = client.cfg.get("models", {}).get("summarizer") or client.cfg["models"]["coder_fallback"]
            chat = client.chat(
                [
                    {"role": "system", "content": SUMMARIZE_SYSTEM},
                    {"role": "user", "content": user},
                ],
                model=model,
                max_tokens=400,
                temperature=0.1,
                role="summarizer",
            )
        if store is not None:
            store.insert_llm_call(
                model=chat.model,
                role="summarizer",
                mutation_id=mutation_id,
                tokens_in=chat.tokens_in,
                tokens_out=chat.tokens_out,
                estimated_usd=chat.estimated_usd,
                latency_ms=chat.latency_ms,
                meta={"stage": "summarize"},
            )
        data = _parse_json(chat.content)
        if not data.get("bullets"):
            offline = distill_episodes_offline(episode_summaries)
            offline["raw"] = chat.content[:2000]
            offline["dry_run"] = False
            offline["model"] = chat.model
            return offline
        return {
            "bullets": [str(b) for b in (data.get("bullets") or [])][:5],
            "failure_modes": [str(x) for x in (data.get("failure_modes") or [])][:4],
            "hints": [str(x) for x in (data.get("hints") or [])][:3],
            "dry_run": False,
            "model": chat.model,
        }
    except Exception as e:
        offline = distill_episodes_offline(episode_summaries)
        offline["error"] = str(e)
        return offline


def format_distill_for_prompt(distill: dict[str, Any]) -> str:
    bullets = distill.get("bullets") or []
    modes = distill.get("failure_modes") or []
    hints = distill.get("hints") or []
    parts = []
    if bullets:
        parts.append("Experience bullets: " + "; ".join(bullets))
    if modes:
        parts.append("Failure modes: " + ", ".join(modes))
    if hints:
        parts.append("Hints: " + "; ".join(hints))
    return "\n".join(parts)


def _parse_json(text: str) -> dict[str, Any]:
    import re

    text = (text or "").strip()
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)```\s*$", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            pass
    return {}
