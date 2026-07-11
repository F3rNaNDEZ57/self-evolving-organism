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
- uses non-existent Observation fields (ticks, pos, health, food, grid) — ONLY:
  tick, energy, energy_max, x, y, local_food, vision, last_reward, alive
- random.choice(..., weights=...) — invalid (choice has no weights)
- Policy.__init__ signature break (must accept use_weights, weight_cfg, explore, train)
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
    "soft_pass": "Soft reject overridden - low-confidence non-hard code; allow eval",
    "other": "Rejected for other review reasons",
}

# NIM soft rejects with low confidence may still proceed to Docker eval
DEFAULT_SOFT_CODES = frozenset({"other", "low_value"})
# Never soft-pass these (static or NIM)
HARD_REJECT_CODES = frozenset(
    {"unsafe_import", "contract_break", "overly_large", "nonsense"}
)


@dataclass
class CriticVerdict:
    decision: str  # approve | reject
    code: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    model: str = ""
    raw: str = ""
    dry_run: bool = False
    soft_passed: bool = False  # True if reject was overridden by soft threshold

    @property
    def approved(self) -> bool:
        return self.decision == "approve"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def apply_soft_threshold(
    verdict: CriticVerdict,
    *,
    soft_threshold: float = 0.6,
    soft_codes: frozenset[str] | set[str] | None = None,
) -> CriticVerdict:
    """
    If NIM (or soft) reject has code in soft_codes and confidence < soft_threshold,
    convert to approve so the fitness gate can decide. Hard codes never soft-pass.
    Static hard rejects already use confidence=1.0 and hard codes.
    """
    if verdict.approved or verdict.soft_passed:
        return verdict
    codes = frozenset(c.lower() for c in (soft_codes if soft_codes is not None else DEFAULT_SOFT_CODES))
    code = (verdict.code or "other").lower()
    if code in HARD_REJECT_CODES or code not in codes:
        return verdict
    if float(verdict.confidence) >= float(soft_threshold):
        return verdict
    # Soft-pass: allow eval (fitness gate decides)
    reasons = list(verdict.reasons) + [
        f"soft_pass: code={code} conf={verdict.confidence:.2f} < {soft_threshold}"
    ]
    return CriticVerdict(
        decision="approve",
        code="soft_pass",
        confidence=float(verdict.confidence),
        reasons=reasons[:12],
        model=verdict.model,
        raw=verdict.raw,
        dry_run=verdict.dry_run,
        soft_passed=True,
    )


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


def _func_dumps(source: str) -> dict[str, str]:
    """Map top-level function name → AST dump (for change detection)."""
    import ast

    out: dict[str, str] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = ast.dump(node, annotate_fields=False)
    return out


def static_food_heuristic_repeat(
    files: dict[str, str],
    *,
    parent_dir: Path | None,
    lessons_text: str = "",
) -> CriticVerdict | None:
    """
    When lessons already flag repeated food-direction low_value work, hard-reject
    patches that only re-tweak nearest_food_direction / should_forage.
    """
    if parent_dir is None:
        return None
    lt = (lessons_text or "").lower()
    if not any(
        x in lt
        for x in (
            "nearest_food",
            "food-direction",
            "food_direction",
            "low_value",
            "diversity",
        )
    ):
        return None
    # Only applies to heuristics-only patches (other modules = different surface)
    if set(files.keys()) != {"heuristics.py"}:
        return None
    parent_h = Path(parent_dir) / "heuristics.py"
    if not parent_h.exists():
        return None
    try:
        parent_src = parent_h.read_text(encoding="utf-8")
    except OSError:
        return None
    new_src = files["heuristics.py"]
    old_f = _func_dumps(parent_src)
    new_f = _func_dumps(new_src)
    if not old_f or not new_f:
        return None
    changed = [name for name in new_f if old_f.get(name) != new_f.get(name)]
    added = [name for name in new_f if name not in old_f]
    removed = [name for name in old_f if name not in new_f]
    if added or removed:
        return None  # structural change elsewhere — ok
    food_only = {"nearest_food_direction", "should_forage"}
    if changed and set(changed).issubset(food_only):
        return CriticVerdict(
            decision="reject",
            code="low_value",
            confidence=1.0,
            reasons=[
                "static: only re-tweaked food-direction heuristics already flagged "
                f"in lessons ({', '.join(changed)}); try energy/rest/walls/timeout instead",
            ],
            model="static",
            dry_run=True,
        )
    return None


def static_precheck(
    files: dict[str, str],
    *,
    parent_dir: Path | None = None,
    lessons_text: str = "",
) -> CriticVerdict | None:
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
    food = static_food_heuristic_repeat(
        files, parent_dir=parent_dir, lessons_text=lessons_text
    )
    if food is not None:
        return food
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
    lessons_text: str = "",
    soft_threshold: float = 0.6,
    soft_codes: list[str] | None = None,
    parent_dir: Path | str | None = None,
) -> CriticVerdict:
    """
    Review proposed file sources. Static hard-fail first, then free NIM critic
    (or dry_run critic). Soft-threshold: low-confidence other/low_value → allow eval.
    On NIM error: fail_open→approve@0.3 or fail-closed reject.
    """
    pdir = Path(parent_dir) if parent_dir else None
    hard = static_precheck(files, parent_dir=pdir, lessons_text=lessons_text)
    if hard is not None:
        return hard  # never soft-pass static hard fails (conf=1.0 + hard codes)

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
    lessons_block = (lessons_text.strip() + "\n") if lessons_text else ""
    prompt = (
        f"Review this mutation proposal.\n"
        f"{distill_txt}\n"
        f"{lessons_block}"
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

    verdict = CriticVerdict(
        decision=decision,
        code=code,
        confidence=conf,
        reasons=reasons or ([REJECT_TAXONOMY.get(code, code)]),
        model=critic_model,
        raw=raw[:4000],
        dry_run=False,
    )
    scodes = soft_codes if soft_codes is not None else list(DEFAULT_SOFT_CODES)
    return apply_soft_threshold(
        verdict,
        soft_threshold=float(soft_threshold),
        soft_codes=set(scodes),
    )
