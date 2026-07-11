"""Phase 3 free-NIM critic: review proposed genome patches before expensive eval."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from organism.genome_loader import WHITELIST
from organism.nim_client import NimClient
from organism.validate import validate_source

CRITIC_SYSTEM = """You are a strict code-review critic for a self-evolving digital organism.
Genome may only change: policy.py, heuristics.py, memory_hooks.py.

Reject if:
- unsafe imports/calls (os, sys, subprocess, socket, eval, exec, open, network)
- missing Policy interface (reset, act, on_step_result) when policy.py changes
- change is pointless noise / huge unrelated rewrite / breaks grid organism design

Approve only if the change is small, safe, and plausibly improves food/survival.

Respond with ONLY JSON (no markdown):
{
  "decision": "approve" | "reject",
  "code": "approve" | "unsafe_import" | "contract_break" | "low_value" | "overly_large" | "nonsense" | "other",
  "confidence": 0.0-1.0,
  "reasons": ["short bullet", "..."]
}
"""

REJECT_TAXONOMY = {
    "approve": "Patch looks safe and potentially useful",
    "unsafe_import": "Forbidden import or dangerous call",
    "contract_break": "Policy interface or whitelist contract broken",
    "low_value": "Unlikely to improve fitness / empty change",
    "overly_large": "Patch too large or sprawling",
    "nonsense": "Incoherent or invalid code",
    "fail_open": "NIM critic unavailable; static-only pass (fail_open)",
    "other": "Rejected for other review reasons",
}


@dataclass
class CriticVerdict:
    decision: str  # approve | reject
    code: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    model: str = ""
    raw: str = ""
    dry_run: bool = False

    @property
    def approved(self) -> bool:
        return self.decision == "approve"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_verdict(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)```\s*$", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}


def static_precheck(files: dict[str, str]) -> CriticVerdict | None:
    """Hard reject without LLM if AST/static rules fail on proposed sources."""
    errors: list[str] = []
    total_lines = 0
    for name, source in files.items():
        if name not in WHITELIST:
            errors.append(f"non-whitelist file {name}")
            continue
        errors.extend(validate_source(name, source))
        total_lines += len(source.splitlines())
    if total_lines > 500:
        errors.append(f"overly large combined patch ({total_lines} lines)")
    if not files:
        return CriticVerdict(
            decision="reject",
            code="low_value",
            confidence=1.0,
            reasons=["no files in proposal"],
            model="static",
            dry_run=True,
        )
    if errors:
        code = "unsafe_import" if any("forbidden" in e for e in errors) else "contract_break"
        if any("too large" in e or "overly large" in e for e in errors):
            code = "overly_large"
        return CriticVerdict(
            decision="reject",
            code=code,
            confidence=1.0,
            reasons=errors[:8],
            model="static",
            dry_run=True,
        )
    return None


def dry_run_critic(
    files: dict[str, str],
    *,
    rationale: str = "",
    parent_fitness: float | None = None,
) -> CriticVerdict:
    """Deterministic critic for offline tests / dry-run mutations."""
    hard = static_precheck(files)
    if hard is not None:
        return hard
    # Heuristic soft checks
    reasons: list[str] = []
    joined = "\n".join(files.values())
    if "import os" in joined or "subprocess" in joined:
        return CriticVerdict(
            decision="reject",
            code="unsafe_import",
            confidence=0.95,
            reasons=["dry_run critic found unsafe patterns"],
            model="dry_run_critic",
            dry_run=True,
        )
    if len(joined.splitlines()) > 400:
        return CriticVerdict(
            decision="reject",
            code="overly_large",
            confidence=0.8,
            reasons=["dry_run critic: patch too large"],
            model="dry_run_critic",
            dry_run=True,
        )
    if not rationale.strip() and "dry-run" not in rationale:
        reasons.append("empty rationale (allowed in dry-run)")
    return CriticVerdict(
        decision="approve",
        code="approve",
        confidence=0.7,
        reasons=reasons or ["dry_run critic: static checks passed"],
        model="dry_run_critic",
        dry_run=True,
    )


def review_proposal(
    *,
    files: dict[str, str],
    rationale: str,
    parent_fitness: float | None = None,
    episode_summaries: list[dict[str, Any]] | None = None,
    client: NimClient | None = None,
    dry_run: bool = False,
    model: str | None = None,
    fail_open: bool = True,
    store: Any | None = None,
    mutation_id: str | None = None,
    experience_distill: dict[str, Any] | None = None,
    router: Any | None = None,
) -> CriticVerdict:
    """
    Review proposed file sources. Static hard-fail first, then free NIM critic
    (or dry_run critic). On NIM error: fail_open→approve@0.3 or fail-closed reject.
    """
    hard = static_precheck(files)
    if hard is not None:
        return hard

    if dry_run:
        return dry_run_critic(files, rationale=rationale, parent_fitness=parent_fitness)

    from organism.summarizer import format_distill_for_prompt

    client = client or NimClient()
    critic_model = (
        model
        or client.cfg.get("models", {}).get("critic")
        or client.cfg["models"].get("coder_fallback")
        or client.cfg["models"]["coder_primary"]
    )

    file_blobs = []
    for name, src in files.items():
        file_blobs.append(f"### {name}\n```python\n{src[:6000]}\n```")
    user = {
        "parent_fitness": parent_fitness,
        "rationale": rationale,
        "episode_summaries": (episode_summaries or [])[:4],
        "experience_distill": experience_distill or {},
        "files": list(files.keys()),
    }
    distill_txt = format_distill_for_prompt(experience_distill or {})
    prompt = (
        f"Review this mutation proposal.\n"
        f"{distill_txt}\n"
        f"Context JSON: {json.dumps(user)}\n\n"
        + "\n\n".join(file_blobs)
    )
    try:
        if router is not None:
            chat = router.chat(
                "critique",
                [
                    {"role": "system", "content": CRITIC_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=800,
                temperature=0.1,
            )
        else:
            chat = client.chat(
                [
                    {"role": "system", "content": CRITIC_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                model=critic_model,
                max_tokens=800,
                temperature=0.1,
                role="critic",
            )
        raw = chat.content
        critic_model = chat.model
        if store is not None:
            store.insert_llm_call(
                model=chat.model,
                role="critic",
                mutation_id=mutation_id,
                tokens_in=chat.tokens_in,
                tokens_out=chat.tokens_out,
                estimated_usd=chat.estimated_usd,
                latency_ms=chat.latency_ms,
                meta={"stage": "critic"},
            )
    except Exception as e:
        if fail_open:
            return CriticVerdict(
                decision="approve",
                code="fail_open",
                confidence=0.3,
                reasons=[f"critic unavailable, fail_open static-only pass: {e}"],
                model=critic_model,
                raw=str(e),
                dry_run=False,
            )
        return CriticVerdict(
            decision="reject",
            code="other",
            confidence=0.9,
            reasons=[f"critic unavailable, fail_closed reject: {e}"],
            model=critic_model,
            raw=str(e),
            dry_run=False,
        )

    data = _parse_verdict(raw)
    decision = str(data.get("decision", "reject")).lower().strip()
    if decision not in ("approve", "reject"):
        decision = "reject"
    code = str(data.get("code", "other" if decision == "reject" else "approve"))
    if decision == "approve":
        code = "approve"
    try:
        conf = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    reasons = data.get("reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    reasons = [str(r) for r in reasons][:10]

    return CriticVerdict(
        decision=decision,
        code=code,
        confidence=conf,
        reasons=reasons or ([REJECT_TAXONOMY.get(code, code)]),
        model=critic_model,
        raw=raw[:4000],
        dry_run=False,
    )
