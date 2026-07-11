"""Genomic mutation: propose (NIM) → apply → validate → eval → accept/reject."""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from organism.config import resolve_path
from organism.critic import CriticVerdict, review_proposal  # soft threshold inside review_proposal
from organism.evaluator import EvalResult, FitnessConfig, episode_score, evaluate, run_episode
from organism.genome_loader import WHITELIST, copy_genome, make_policy_factory
from organism.nim_client import NimClient
from organism.persistence import Store
from organism.validate import GenomeValidationError, assert_valid_genome, validate_genome_dir
from organism.weights import WeightConfig
from organism.world import WorldConfig

MUTATION_SYSTEM = """You are the mutation coder for a self-evolving digital organism on a 24x24 grid.
You are part of a closed-loop improver: you SEE past accepts/rejects with fitness deltas and MUST learn from them.

You may ONLY change whitelist modules: policy.py, heuristics.py, memory_hooks.py.

Rules:
- Beat the parent fitness bar (ε-accept). Cosmetic or identical files fail.
- Prefer ENERGY management, REST vs move tradeoffs, or TIMEOUT survival (not food micro-tweaks).
- Avoid re-editing nearest_food_direction / should_forage when history flags low_value.
- Observation fields ONLY: tick, energy, energy_max, x, y, local_food, vision, last_reward, alive.
  Never invent position, local_walls, health, grid, ticks.
- Do NOT import os, sys, subprocess, socket, pathlib, shutil, or use eval/exec/open.
- Allowed: random, math, typing, numpy, organism.schemas, organism.weights, sibling modules.
- policy.py MUST define class Policy with: reset(seed), act(observation), on_step_result(result).
- Keep changes small (prefer under 80 new/changed lines of logic).

Respond with ONLY a JSON object (no markdown fences):
{
  "rationale": "cite which history lesson you learn from + failure mode (energy|rest|timeout|food)",
  "files": {
    "heuristics.py": "FULL file source if changed",
    "policy.py": "FULL file source if changed",
    "memory_hooks.py": "FULL file source if changed"
  }
}
Response rules:
- At least one file key; COMPLETE sources (not diffs, not empty, not parent clones).
- Prefer ONLY heuristics.py when possible.
- Keep each file under ~120 lines; close all braces/quotes.
- Never prose-only; never {"files": {}}.
"""


@dataclass
class MutationResult:
    mutation_id: str
    parent_genome_id: str
    candidate_genome_id: str
    decision: str  # accepted | rejected | failed
    reason: str
    parent_fitness: float
    candidate_fitness: float | None
    epsilon: float
    parent_path: str
    candidate_path: str
    model: str
    rationale: str = ""
    proposal_raw: str = ""
    files_changed: list[str] = field(default_factory=list)
    critic_decision: str = ""  # approve | reject | skipped
    critic_code: str = ""
    critic_confidence: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _uid(prefix: str = "m") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _files_from_mapping(files: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(files, dict):
        return out
    for k, v in files.items():
        name = Path(str(k)).name
        if name in WHITELIST and isinstance(v, str) and v.strip():
            # Models sometimes double-escape newlines
            src = v.replace("\r\n", "\n")
            if "\\n" in src and "\n" not in src.strip()[:80]:
                try:
                    src = src.encode("utf-8").decode("unicode_escape")
                except Exception:
                    src = src.replace("\\n", "\n").replace("\\t", "\t")
            out[name] = src
    return out


def _decode_json_string_body(raw: str) -> str:
    """Decode a JSON string body (may be truncated)."""
    try:
        return json.loads(f'"{raw}"')
    except Exception:
        try:
            return raw.encode("utf-8").decode("unicode_escape")
        except Exception:
            return raw.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')


def _extract_files_from_truncated_json(text: str) -> dict[str, str]:
    """
    Recover whitelist file bodies when the model truncates mid-JSON.
    Looks for "policy.py": "...." patterns with JSON escapes.
    """
    out: dict[str, str] = {}
    for base in ("policy", "heuristics", "memory_hooks"):
        name = f"{base}.py"
        m = re.search(rf'"{re.escape(name)}"\s*:\s*"', text)
        if not m:
            # also allow unquoted-ish markdown leftovers
            m2 = re.search(
                rf'"{re.escape(base)}\.py"\s*:\s*"""([\s\S]*?)"""',
                text,
            )
            if m2 and m2.group(1).strip():
                out[name] = m2.group(1).strip() + "\n"
            continue
        i = m.end()
        chars: list[str] = []
        while i < len(text):
            c = text[i]
            if c == "\\" and i + 1 < len(text):
                chars.append(text[i : i + 2])
                i += 2
                continue
            if c == '"':
                break
            chars.append(c)
            i += 1
        raw = "".join(chars)
        if not raw.strip():
            continue
        body = _decode_json_string_body(raw)
        # Accept only if it looks like Python source for our genome
        if len(body.strip()) < 20:
            continue
        if name == "policy.py" and "class Policy" not in body and "def act" not in body:
            # truncated too early — still keep if has imports (retry will fix)
            if "import" not in body and "def " not in body:
                continue
        out[name] = body if body.endswith("\n") else body + "\n"
    return out


def extract_files_from_proposal(text: str) -> dict[str, str]:
    """Parse LLM proposal into {filename: source}."""
    text = (text or "").strip()
    if not text:
        return {}
    # Strip markdown fences wrapping whole JSON only (not per-file code fences)
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)```\s*$", text)
    if fence:
        text = fence.group(1).strip()
    elif text.lstrip().startswith("```json"):
        # unclosed ```json ... — drop the opener only
        text = re.sub(r"^```json\s*", "", text.lstrip())

    # Prefer full JSON
    try:
        data = json.loads(text)
        out = _files_from_mapping(data.get("files") if isinstance(data, dict) else {})
        if out:
            return out
    except json.JSONDecodeError:
        pass

    # JSON object substring / raw_decode from first brace
    start = text.find("{")
    if start != -1:
        try:
            data, _ = json.JSONDecoder().raw_decode(text[start:])
            out = _files_from_mapping(data.get("files") if isinstance(data, dict) else {})
            if out:
                return out
        except json.JSONDecodeError:
            pass
        end = text.rfind("}")
        if end > start:
            try:
                data = json.loads(text[start : end + 1])
                out = _files_from_mapping(
                    data.get("files") if isinstance(data, dict) else {}
                )
                if out:
                    return out
            except json.JSONDecodeError:
                pass

    # Truncated JSON recovery (common free-NIM failure mode)
    recovered = _extract_files_from_truncated_json(text)
    if recovered:
        return recovered

    # Markdown: ### file.py or **file.py** then ```python
    out: dict[str, str] = {}
    pattern = re.compile(
        r"(?:^|\n)(?:#{1,3}\s*|[*]{0,2})(policy|heuristics|memory_hooks)\.py(?:[*]{0,2})?\s*\n```(?:python)?\n([\s\S]*?)```",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        name = f"{m.group(1).lower()}.py"
        if name in WHITELIST:
            out[name] = m.group(2).strip() + "\n"
    if out:
        return out

    # Bare fenced blocks labeled in preceding line
    pattern2 = re.compile(
        r"(policy|heuristics|memory_hooks)\.py[\s\S]{0,40}```(?:python)?\n([\s\S]*?)```",
        re.IGNORECASE,
    )
    for m in pattern2.finditer(text):
        name = f"{m.group(1).lower()}.py"
        if name in WHITELIST and m.group(2).strip():
            out[name] = m.group(2).strip() + "\n"
    return out


def extract_rationale(text: str) -> str:
    try:
        data = json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip())
        if isinstance(data, dict) and data.get("rationale"):
            return str(data["rationale"])
    except Exception:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            if isinstance(data, dict) and data.get("rationale"):
                return str(data["rationale"])
        except Exception:
            pass
    return ""


def _norm_src(s: str) -> str:
    return "\n".join(line.rstrip() for line in (s or "").replace("\r\n", "\n").splitlines()).strip()


def proposal_file_issues(
    files: dict[str, str],
    *,
    parent_dir: Path | None = None,
) -> list[str]:
    """
    Static proposal quality checks (no LLM).
    Returns human-readable issues; empty list means files look usable.
    """
    issues: list[str] = []
    if not files:
        issues.append("no whitelist files in proposal")
        return issues
    for name, src in files.items():
        body = (src or "").strip()
        if len(body) < 40:
            issues.append(f"{name}: body too short ({len(body)} chars)")
            continue
        if name == "policy.py" and "class Policy" not in body:
            issues.append(f"{name}: missing class Policy")
        if name == "policy.py" and "def act" not in body:
            issues.append(f"{name}: missing def act")
        if name.endswith(".py") and "def " not in body and "class " not in body:
            issues.append(f"{name}: no def/class — not a full module")
    if parent_dir is not None:
        parent_dir = Path(parent_dir)
        identical = 0
        for name, src in files.items():
            p = parent_dir / name
            if not p.exists():
                continue
            try:
                parent_src = p.read_text(encoding="utf-8")
            except OSError:
                continue
            if _norm_src(src) == _norm_src(parent_src):
                identical += 1
                issues.append(f"{name}: identical to parent (no-op)")
        if files and identical == len(files):
            issues.append("all proposed files are identical to parent")
    return issues


def is_usable_proposal(
    files: dict[str, str],
    *,
    parent_dir: Path | None = None,
) -> tuple[bool, str]:
    """Return (ok, reason). ok=False → skip critic/eval."""
    issues = proposal_file_issues(files, parent_dir=parent_dir)
    if not issues:
        return True, ""
    # Allow non-identical files even if one extra note; only fail hard issues
    hard = [
        i
        for i in issues
        if "identical to parent" in i
        or "too short" in i
        or "no whitelist" in i
        or "missing class" in i
        or "missing def" in i
        or "no def/class" in i
        or "all proposed" in i
    ]
    if hard:
        return False, "; ".join(hard[:4])
    return True, ""


def apply_files(parent_dir: Path, candidate_dir: Path, files: dict[str, str]) -> list[str]:
    """Copy parent genome then overwrite whitelist files from proposal."""
    if candidate_dir.exists():
        shutil.rmtree(candidate_dir)
    copy_genome(parent_dir, candidate_dir)
    changed: list[str] = []
    for name, source in files.items():
        if name not in WHITELIST:
            continue
        # normalize newlines
        src = source.replace("\r\n", "\n")
        if not src.endswith("\n"):
            src += "\n"
        (candidate_dir / name).write_text(src, encoding="utf-8")
        changed.append(name)
    if not changed:
        raise ValueError("proposal contained no whitelist file changes")
    return changed


def propose_policy_patch(
    genome_dir: Path,
    episode_summaries: list[dict[str, Any]],
    *,
    client: NimClient | None = None,
    parent_fitness: float | None = None,
    store: Store | None = None,
    mutation_id: str | None = None,
    router: Any | None = None,
    experience_distill: dict[str, Any] | None = None,
    lessons_text: str = "",
) -> dict[str, Any]:
    from organism.router import FreeNimRouter
    from organism.summarizer import format_distill_for_prompt

    client = client or (router.client() if router is not None else NimClient())
    sources = []
    for name in WHITELIST:
        p = genome_dir / name
        if p.exists():
            sources.append(f"### {name}\n```python\n{p.read_text(encoding='utf-8')[:5000]}\n```")
    fit_line = f"Parent fitness (train seeds): {parent_fitness:.4f}\n" if parent_fitness is not None else ""
    distill_line = ""
    if experience_distill:
        distill_line = format_distill_for_prompt(experience_distill) + "\n"
    lessons_line = (lessons_text.strip() + "\n") if lessons_text else ""
    user = (
        f"{fit_line}"
        f"{distill_line}"
        f"{lessons_line}"
        "You have mutation HISTORY above — use accepts as patterns and rejects as hard constraints.\n"
        "Improve survival vs parent fitness. Return ONLY complete JSON "
        "(rationale + files) with FULL file sources for every changed module.\n"
        "Target energy / rest-vs-move / timeout survival first (food micro-tweaks last).\n"
        "Prefer a single small change to heuristics.py if possible.\n"
        "If history forbids food-direction edits, change a DIFFERENT behavior.\n"
        "Do NOT invent Observation fields; do NOT rewrite policy.py unless required.\n"
        "Do NOT return empty files, diffs, or identical parent sources.\n"
        f"Recent episode summaries: {json.dumps(episode_summaries[:8])}\n\n"
        + "\n\n".join(sources)
    )
    coder_max_tokens = 8192
    chat_usage: dict[str, Any] | None = None
    text = ""
    model = ""
    retries: list[str] = []

    def _one_chat(
        messages: list[dict[str, str]],
        *,
        role: str,
        max_tokens: int,
        force_fallback: bool = False,
    ) -> Any:
        if router is not None:
            rtr: FreeNimRouter = router
            use_role = "coder_fallback" if force_fallback else "code"
            fb = None if force_fallback else "coder_fallback"
            return rtr.chat(
                use_role,
                messages,
                max_tokens=max_tokens,
                temperature=0.25 if force_fallback else 0.2,
                fallback_role=fb,
            )
        nonlocal model
        models = client.cfg.get("models") or {}
        if force_fallback:
            model = models.get("coder_fallback") or models.get("coder_primary")
            return client.chat(
                messages,
                model=model,
                max_tokens=max_tokens,
                temperature=0.25,
                role="coder_fallback",
            )
        model = models.get("coder_primary") or model
        try:
            return client.chat(
                messages,
                model=model,
                max_tokens=max_tokens,
                temperature=0.2,
                role=role,
            )
        except Exception:
            model = models.get("coder_fallback", model)
            return client.chat(
                messages,
                model=model,
                max_tokens=max_tokens,
                temperature=0.2,
                role="coder_fallback",
            )

    def _log_chat(usage: dict[str, Any] | None, stage: str, used_model: str) -> None:
        if store is None or usage is None:
            return
        store.insert_llm_call(
            model=str(usage.get("model", used_model)),
            role=str(usage.get("role") or "coder"),
            mutation_id=mutation_id,
            tokens_in=usage.get("tokens_in"),
            tokens_out=usage.get("tokens_out"),
            estimated_usd=float(usage.get("estimated_usd") or 0.0),
            latency_ms=float(usage.get("latency_ms") or 0.0),
            meta={"stage": stage},
        )

    messages = [
        {"role": "system", "content": MUTATION_SYSTEM},
        {"role": "user", "content": user},
    ]
    chat = _one_chat(messages, role="coder", max_tokens=coder_max_tokens)
    text = chat.content or ""
    model = getattr(chat, "model", None) or model or ""
    chat_usage = chat.to_dict() if hasattr(chat, "to_dict") else None
    _log_chat(chat_usage, "propose", model)
    files = extract_files_from_proposal(text)
    ok, why = is_usable_proposal(files, parent_dir=genome_dir)
    if not ok:
        retries.append(f"primary_unusable:{why or 'empty'}")
        files = {}

    def _retry_propose(*, force_fallback: bool, stage: str, extra: str) -> None:
        nonlocal text, files, model, chat_usage
        retry_user = (
            f"{extra}\n"
            "Return ONLY a complete JSON object with rationale and files.\n"
            "Change ONLY heuristics.py — FULL file source (not a diff), under 100 lines.\n"
            "Target energy management OR rest-vs-move OR wall avoidance (not food-direction micro-tweaks).\n"
            "Do not use markdown fences. Close all braces and quotes.\n"
            "files.heuristics.py must differ from the parent and include real functions.\n\n"
            f"Parent fitness: {parent_fitness}\n"
            f"Episode summaries: {json.dumps(episode_summaries[:4])}\n\n"
        )
        heur_path = genome_dir / "heuristics.py"
        if heur_path.exists():
            retry_user += (
                "### parent heuristics.py (modify a different behavior than food-only)\n"
                "```python\n"
                f"{heur_path.read_text(encoding='utf-8')[:4000]}\n```\n"
            )
        retry_messages = [
            {"role": "system", "content": MUTATION_SYSTEM},
            {"role": "user", "content": retry_user},
        ]
        try:
            chat2 = _one_chat(
                retry_messages,
                role="coder",
                max_tokens=coder_max_tokens,
                force_fallback=force_fallback,
            )
            text2 = chat2.content or ""
            model = getattr(chat2, "model", None) or model
            usage2 = chat2.to_dict() if hasattr(chat2, "to_dict") else None
            _log_chat(usage2, stage, model)
            files2 = extract_files_from_proposal(text2)
            ok2, why2 = is_usable_proposal(files2, parent_dir=genome_dir)
            if ok2 and files2:
                text = text2
                files = files2
                chat_usage = usage2
            else:
                retries.append(f"{stage}:{why2 or 'empty'}")
        except Exception as e:
            retries.append(f"{stage}_error:{type(e).__name__}")

    # Retry 1: same path after parse/no-op fail
    if not files:
        _retry_propose(
            force_fallback=False,
            stage="propose_retry",
            extra="Your previous reply was empty, unparseable, truncated, or a no-op.",
        )
    # Retry 2: force secondary free coder model after parse fail
    if not files:
        _retry_propose(
            force_fallback=True,
            stage="propose_fallback",
            extra=(
                "Previous attempts failed to produce usable file bodies. "
                "You are the fallback coder — produce valid JSON with full heuristics.py."
            ),
        )

    return {
        "model": model,
        "proposal": text,
        "rationale": extract_rationale(text),
        "files": files,
        "applied": False,
        "llm_usage": chat_usage,
        "experience_distill": experience_distill,
        "retries": retries,
        "usable": bool(files)
        and is_usable_proposal(files, parent_dir=genome_dir)[0],
    }


def _episode_context(
    genome_dir: Path,
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    ablation: str,
    seeds: list[int],
) -> list[dict[str, Any]]:
    # Context for prompts stays host-side (trusted parent summaries; cheap).
    factory = make_policy_factory(genome_dir, ablation=ablation, weight_cfg=wcfg)
    train = ablation in ("Bw", "Bcw")
    out = []
    for s in seeds[:4]:
        ep = run_episode(factory(), world, s, train_weights=train)
        ep.score = episode_score(ep, fit)
        out.append(
            {
                "seed": ep.seed,
                "score": round(ep.score, 4),
                "food": ep.food_collected,
                "ticks": ep.ticks_survived,
                "death": ep.death_reason,
            }
        )
    return out


def _eval_genome(
    genome_dir: Path,
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    seeds: list[int],
    ablation: str,
    *,
    sandbox_cfg: Any | None = None,
    force_host: bool = False,
    force_docker: bool = False,
    weight_path: Path | None = None,
) -> EvalResult:
    from organism.sandbox import SandboxConfig, evaluate_genome

    train = ablation in ("Bw", "Bcw") and weight_path is None
    # When isolating candidates we still allow host for unit tests via force_host.
    sb = sandbox_cfg if sandbox_cfg is not None else SandboxConfig()
    return evaluate_genome(
        genome_dir,
        world=world,
        fit=fit,
        wcfg=wcfg,
        seeds=seeds,
        ablation=ablation,
        sandbox=sb,
        train_weights=train,
        weight_path=weight_path,
        force_host=force_host,
        force_docker=force_docker,
    )


def run_mutation_cycle(
    *,
    parent_dir: Path,
    artifacts_dir: Path,
    store: Store,
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    train_seeds: list[int],
    ablation: str = "Bc",
    parent_genome_id: str = "g_seed",
    client: NimClient | None = None,
    dry_run: bool = False,
    proposal_override: dict[str, Any] | None = None,
    sandbox_cfg: Any | None = None,
    force_host_eval: bool = False,
    critic: bool | None = None,
    critic_model: str | None = None,
    critic_cfg: dict[str, Any] | None = None,
) -> MutationResult:
    """
    Full loop: eval parent → NIM propose → critic → apply → validate → eval → accept/reject.
    Critic (static + free NIM / dry-run) runs before expensive candidate eval.
    Candidate eval uses Docker episode isolation when sandbox.episode_isolation is true.
    """
    from organism.sandbox import SandboxConfig

    parent_dir = Path(parent_dir)
    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    mut_id = _uid("m")
    cand_id = _uid("g")
    epsilon = float(fit.epsilon_accept)
    sb = sandbox_cfg if sandbox_cfg is not None else SandboxConfig()
    ccfg = dict(critic_cfg or {})
    use_critic = bool(ccfg.get("enabled", True)) if critic is None else bool(critic)
    # Dry-run unit paths stay on host; live mutations isolate candidates in Docker.
    if dry_run and not force_host_eval:
        force_host_eval = True

    # Fitness gate for genomic mutations: always score frozen code path (Bc), never
    # train random weights mid-eval (that produced ~0 fitness noise on Bcw).
    fit_ablation = "Bc" if ablation in ("Bc", "Bcw") else ablation

    # 1) Parent fitness (host unless parent_isolation)
    parent_force_host = force_host_eval or not sb.parent_isolation
    parent_eval = _eval_genome(
        parent_dir,
        world,
        fit,
        wcfg,
        train_seeds,
        fit_ablation,
        sandbox_cfg=sb,
        force_host=parent_force_host,
        force_docker=sb.parent_isolation and not force_host_eval,
    )
    store.insert_evaluation(
        parent_genome_id,
        parent_eval.fitness,
        parent_eval.mean_score,
        parent_eval.std_score,
        parent_eval.seeds,
        parent_eval.episodes,
    )
    store.log_event(
        "mutation_parent_eval",
        {"mutation_id": mut_id, "genome_id": parent_genome_id, "fitness": parent_eval.fitness},
    )

    summaries = _episode_context(parent_dir, world, fit, wcfg, fit_ablation, train_seeds)

    # 1b) Structured mutation memory (SQL lessons — no vectors)
    from organism.mutation_memory import format_lessons_for_prompt, retrieve_mutation_lessons
    from organism.router import FreeNimRouter
    from organism.summarizer import distill_episodes

    lessons = retrieve_mutation_lessons(
        store, k=12, parent_genome_id=parent_genome_id
    )
    lessons_text = format_lessons_for_prompt(lessons)
    if lessons:
        store.log_event(
            "mutation_memory",
            {"mutation_id": mut_id, "n": len(lessons), "ids": [L.get("mutation_id") for L in lessons]},
        )

    # 1c) Experience distillation (summarizer pin / offline) for coder + critic context
    pool_cfg = dict(ccfg)
    use_summarizer = bool(pool_cfg.get("use_summarizer", True))
    router: FreeNimRouter | None = None
    if not dry_run:
        # Merge experiment pool.budget into NIM pins if present on critic_cfg parent path
        rcfg = None
        try:
            from organism.config import experiment_config, nim_config

            ncfg = nim_config()
            exp = experiment_config()
            pool = exp.get("pool") or {}
            if pool.get("budget"):
                ncfg = dict(ncfg)
                ncfg["budget"] = {**(ncfg.get("budget") or {}), **pool["budget"]}
            rcfg = ncfg
        except Exception:
            rcfg = None
        router = FreeNimRouter(rcfg)
        client = client or router.client()
    experience_distill: dict[str, Any] | None = None
    if use_summarizer:
        experience_distill = distill_episodes(
            summaries,
            client=client,
            router=router,
            dry_run=dry_run,
            store=store,
            mutation_id=mut_id,
        )
        store.log_event(
            "mutation_summarize",
            {"mutation_id": mut_id, "distill": experience_distill},
        )

    # 2) Propose
    if proposal_override is not None:
        proposal = proposal_override
        model = str(proposal.get("model", "override"))
    else:
        if dry_run:
            # deterministic tiny improvement proposal for offline tests
            heur = (parent_dir / "heuristics.py").read_text(encoding="utf-8")
            # bump forage aggressiveness comment-only if needed — use full file with slight logic tweak
            if "return float(grid[v, v]) > 0" in heur:
                heur2 = heur.replace(
                    "return float(grid[v, v]) > 0",
                    "return float(grid[v, v]) > 0  # forage when standing on food",
                )
            else:
                heur2 = heur
            # Improve policy: more deterministic food chase
            pol = (parent_dir / "policy.py").read_text(encoding="utf-8")
            pol2 = pol.replace("self.rng.random() < 0.7", "self.rng.random() < 0.95")
            pol2 = pol2.replace("self.rng.random() < 0.85", "self.rng.random() < 0.98")
            proposal = {
                "model": "dry_run",
                "proposal": json.dumps(
                    {
                        "rationale": "dry-run: greedier food chase",
                        "files": {"policy.py": pol2, "heuristics.py": heur2},
                    }
                ),
                "rationale": "dry-run: greedier food chase",
                "files": {"policy.py": pol2, "heuristics.py": heur2},
                "experience_distill": experience_distill,
            }
            model = "dry_run"
        else:
            assert router is not None
            proposal = propose_policy_patch(
                parent_dir,
                summaries,
                client=client,
                parent_fitness=parent_eval.fitness,
                store=store,
                mutation_id=mut_id,
                router=router,
                experience_distill=experience_distill,
                lessons_text=lessons_text,
            )
            model = str(proposal.get("model", ""))
            router.budget.record_mutation()

    files = proposal.get("files") or extract_files_from_proposal(str(proposal.get("proposal", "")))
    rationale = str(proposal.get("rationale") or extract_rationale(str(proposal.get("proposal", ""))))
    cand_path = artifacts_dir / "genomes" / cand_id
    critic_verdict: CriticVerdict | None = None

    usable, usable_why = is_usable_proposal(files, parent_dir=parent_dir)
    if not files or not usable:
        raw_preview = str(proposal.get("proposal", ""))[:200].replace("\n", " ")
        retries = proposal.get("retries") or []
        reason = (
            "proposal quality gate: "
            f"{usable_why or 'no whitelist files'} "
            f"(retries={retries!r}; often empty/truncated/no-op JSON). "
            f"preview={raw_preview!r}"
        )
        store.insert_mutation(
            mut_id,
            parent_genome_id,
            cand_id,
            "failed",
            reason,
            {
                "model": model,
                "rationale": rationale,
                "proposal": str(proposal.get("proposal", ""))[:8000],
                "retries": retries,
                "quality_gate": usable_why or "empty",
            },
        )
        store.log_event(
            "mutation_failed",
            {
                "mutation_id": mut_id,
                "reason": reason,
                "quality_gate": True,
                "retries": retries,
            },
        )
        return MutationResult(
            mutation_id=mut_id,
            parent_genome_id=parent_genome_id,
            candidate_genome_id=cand_id,
            decision="failed",
            reason=reason,
            parent_fitness=parent_eval.fitness,
            candidate_fitness=None,
            epsilon=epsilon,
            parent_path=str(parent_dir),
            candidate_path=str(cand_path),
            model=model,
            rationale=rationale,
            proposal_raw=str(proposal.get("proposal", ""))[:8000],
            files_changed=[],
            critic_decision="skipped",
            meta={"quality_gate": True, "retries": list(retries)},
        )

    # 2b) Critic before expensive apply/eval (static hard-fail + free NIM / dry-run)
    if use_critic:
        fail_open = bool(ccfg.get("fail_open", True))
        soft_thr = float(ccfg.get("soft_threshold", 0.6))
        soft_codes = ccfg.get("soft_codes") or ["other", "low_value"]
        critic_verdict = review_proposal(
            files=files,
            rationale=rationale,
            parent_fitness=parent_eval.fitness,
            episode_summaries=summaries,
            client=None if dry_run else (client or NimClient()),
            dry_run=dry_run,
            model=critic_model or ccfg.get("model"),
            fail_open=fail_open,
            store=store,
            mutation_id=mut_id,
            experience_distill=experience_distill,
            router=router,
            lessons_text=lessons_text,
            soft_threshold=soft_thr,
            soft_codes=list(soft_codes),
            parent_dir=parent_dir,
        )
        store.log_event(
            "mutation_critic",
            {
                "mutation_id": mut_id,
                "decision": critic_verdict.decision,
                "code": critic_verdict.code,
                "confidence": critic_verdict.confidence,
                "model": critic_verdict.model,
                "reasons": critic_verdict.reasons,
                "dry_run": critic_verdict.dry_run,
                "fail_open_used": critic_verdict.code == "fail_open",
                "soft_passed": critic_verdict.soft_passed,
            },
        )
        if not critic_verdict.approved:
            reason = (
                f"critic reject [{critic_verdict.code}]: "
                + "; ".join(critic_verdict.reasons[:4])
            )
            # Optional audit copy of rejected proposal sources (no full genome apply)
            rej_dir = artifacts_dir / "mutations" / f"{mut_id}_rejected_sources"
            rej_dir.mkdir(parents=True, exist_ok=True)
            for name, src in files.items():
                (rej_dir / name).write_text(
                    src if src.endswith("\n") else src + "\n", encoding="utf-8"
                )
            store.insert_genome(
                genome_id=cand_id,
                parent_id=parent_genome_id,
                status="critic_rejected",
                ablation=ablation,
                artifact_path=str(rej_dir),
            )
            store.insert_mutation(
                mut_id,
                parent_genome_id,
                cand_id,
                "rejected",
                reason,
                {
                    "model": model,
                    "rationale": rationale,
                    "files_changed": list(files.keys()),
                    "parent_fitness": parent_eval.fitness,
                    "candidate_fitness": None,
                    "epsilon": epsilon,
                    "critic": critic_verdict.to_dict(),
                    "proposal": str(proposal.get("proposal", ""))[:8000],
                },
            )
            store.log_event(
                "mutation_rejected",
                {
                    "mutation_id": mut_id,
                    "parent": parent_genome_id,
                    "candidate": cand_id,
                    "reason": reason,
                    "via": "critic",
                },
            )
            prop_path = artifacts_dir / "mutations" / f"{mut_id}.json"
            prop_path.parent.mkdir(parents=True, exist_ok=True)
            prop_path.write_text(
                json.dumps(
                    {
                        "mutation_id": mut_id,
                        "decision": "rejected",
                        "reason": reason,
                        "model": model,
                        "rationale": rationale,
                        "files_changed": list(files.keys()),
                        "parent_fitness": parent_eval.fitness,
                        "candidate_fitness": None,
                        "critic": critic_verdict.to_dict(),
                        "proposal": proposal.get("proposal"),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            return MutationResult(
                mutation_id=mut_id,
                parent_genome_id=parent_genome_id,
                candidate_genome_id=cand_id,
                decision="rejected",
                reason=reason,
                parent_fitness=parent_eval.fitness,
                candidate_fitness=None,
                epsilon=epsilon,
                parent_path=str(parent_dir),
                candidate_path=str(rej_dir),
                model=model,
                rationale=rationale,
                proposal_raw=str(proposal.get("proposal", ""))[:8000],
                files_changed=list(files.keys()),
                critic_decision=critic_verdict.decision,
                critic_code=critic_verdict.code,
                critic_confidence=critic_verdict.confidence,
                meta={"proposal_path": str(prop_path), "critic": critic_verdict.to_dict()},
            )

    # 2c) Apply + validate
    try:
        changed = apply_files(parent_dir, cand_path, files)
        assert_valid_genome(cand_path)
    except Exception as e:
        reason = f"apply/validate failed: {e}"
        store.insert_mutation(
            mut_id,
            parent_genome_id,
            cand_id,
            "failed",
            reason,
            {
                "model": model,
                "rationale": rationale,
                "proposal": str(proposal.get("proposal", ""))[:8000],
                "critic": critic_verdict.to_dict() if critic_verdict else None,
            },
        )
        store.log_event("mutation_failed", {"mutation_id": mut_id, "reason": reason})
        return MutationResult(
            mutation_id=mut_id,
            parent_genome_id=parent_genome_id,
            candidate_genome_id=cand_id,
            decision="failed",
            reason=reason,
            parent_fitness=parent_eval.fitness,
            candidate_fitness=None,
            epsilon=epsilon,
            parent_path=str(parent_dir),
            candidate_path=str(cand_path),
            model=model,
            rationale=rationale,
            proposal_raw=str(proposal.get("proposal", ""))[:8000],
            files_changed=list(files.keys()) if isinstance(files, dict) else [],
            critic_decision=critic_verdict.decision if critic_verdict else "skipped",
            critic_code=critic_verdict.code if critic_verdict else "",
            critic_confidence=critic_verdict.confidence if critic_verdict else None,
        )

    # 3) Evaluate candidate (Docker-isolated by default)
    try:
        cand_eval = _eval_genome(
            cand_path,
            world,
            fit,
            wcfg,
            train_seeds,
            fit_ablation,
            sandbox_cfg=sb,
            force_host=force_host_eval,
            force_docker=sb.episode_isolation and not force_host_eval,
        )
    except Exception as e:
        reason = f"candidate crashed during eval: {e}"
        store.insert_genome(
            genome_id=cand_id,
            parent_id=parent_genome_id,
            status="crashed",
            ablation=ablation,
            artifact_path=str(cand_path),
        )
        store.insert_mutation(
            mut_id,
            parent_genome_id,
            cand_id,
            "failed",
            reason,
            {"model": model, "rationale": rationale},
        )
        store.log_event("mutation_failed", {"mutation_id": mut_id, "reason": reason})
        return MutationResult(
            mutation_id=mut_id,
            parent_genome_id=parent_genome_id,
            candidate_genome_id=cand_id,
            decision="failed",
            reason=reason,
            parent_fitness=parent_eval.fitness,
            candidate_fitness=None,
            epsilon=epsilon,
            parent_path=str(parent_dir),
            candidate_path=str(cand_path),
            model=model,
            rationale=rationale,
            proposal_raw=str(proposal.get("proposal", ""))[:8000],
            files_changed=changed,
            critic_decision=critic_verdict.decision if critic_verdict else "skipped",
            critic_code=critic_verdict.code if critic_verdict else "",
            critic_confidence=critic_verdict.confidence if critic_verdict else None,
        )

    store.insert_genome(
        genome_id=cand_id,
        parent_id=parent_genome_id,
        status="candidate",
        ablation=ablation,
        artifact_path=str(cand_path),
    )
    store.insert_evaluation(
        cand_id,
        cand_eval.fitness,
        cand_eval.mean_score,
        cand_eval.std_score,
        cand_eval.seeds,
        cand_eval.episodes,
    )

    # 4) Accept / reject
    threshold = parent_eval.fitness + epsilon
    if cand_eval.fitness >= threshold:
        decision = "accepted"
        reason = (
            f"fitness {cand_eval.fitness:.4f} >= parent {parent_eval.fitness:.4f} + eps {epsilon}"
        )
        store.set_genome_status(parent_genome_id, "archived")
        store.set_genome_status(cand_id, "active")
        # promote: write active pointer
        active = artifacts_dir / "active_genome.json"
        active.write_text(
            json.dumps(
                {
                    "genome_id": cand_id,
                    "path": str(cand_path),
                    "parent_id": parent_genome_id,
                    "fitness": cand_eval.fitness,
                    "updated_at": time.time(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        # also mirror to artifacts/genomes/active
        active_dir = artifacts_dir / "genomes" / "active"
        if active_dir.exists():
            shutil.rmtree(active_dir)
        copy_genome(cand_path, active_dir)
    else:
        decision = "rejected"
        reason = (
            f"fitness {cand_eval.fitness:.4f} < parent {parent_eval.fitness:.4f} + eps {epsilon}"
        )
        store.set_genome_status(cand_id, "rejected")

    critic_meta = critic_verdict.to_dict() if critic_verdict else {"decision": "skipped"}
    llm_usage = store.llm_usage_for_mutation(mut_id)
    cost_gain = store.cost_per_accepted_gain(
        parent_fitness=parent_eval.fitness,
        candidate_fitness=cand_eval.fitness,
        tokens_total=int(llm_usage.get("tokens_total") or 0),
    )
    store.insert_mutation(
        mut_id,
        parent_genome_id,
        cand_id,
        decision,
        reason,
        {
            "model": model,
            "rationale": rationale,
            "files_changed": changed,
            "parent_fitness": parent_eval.fitness,
            "candidate_fitness": cand_eval.fitness,
            "epsilon": epsilon,
            "critic": critic_meta,
            "llm_usage": llm_usage,
            "cost_per_accepted_gain_tokens": cost_gain,
            "proposal": str(proposal.get("proposal", ""))[:8000],
        },
    )
    store.log_event(
        f"mutation_{decision}",
        {
            "mutation_id": mut_id,
            "parent": parent_genome_id,
            "candidate": cand_id,
            "parent_fitness": parent_eval.fitness,
            "candidate_fitness": cand_eval.fitness,
            "reason": reason,
            "critic": critic_meta,
        },
    )

    # save proposal artifact
    prop_path = artifacts_dir / "mutations" / f"{mut_id}.json"
    prop_path.parent.mkdir(parents=True, exist_ok=True)
    prop_path.write_text(
        json.dumps(
            {
                "mutation_id": mut_id,
                "decision": decision,
                "reason": reason,
                "model": model,
                "rationale": rationale,
                "files_changed": changed,
                "parent_fitness": parent_eval.fitness,
                "candidate_fitness": cand_eval.fitness,
                "critic": critic_meta,
                "proposal": proposal.get("proposal"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    return MutationResult(
        mutation_id=mut_id,
        parent_genome_id=parent_genome_id,
        candidate_genome_id=cand_id,
        decision=decision,
        reason=reason,
        parent_fitness=parent_eval.fitness,
        candidate_fitness=cand_eval.fitness,
        epsilon=epsilon,
        parent_path=str(parent_dir),
        candidate_path=str(cand_path),
        model=model,
        rationale=rationale,
        proposal_raw=str(proposal.get("proposal", ""))[:8000],
        files_changed=changed,
        critic_decision=critic_verdict.decision if critic_verdict else "skipped",
        critic_code=critic_verdict.code if critic_verdict else "",
        critic_confidence=critic_verdict.confidence if critic_verdict else None,
        meta={"proposal_path": str(prop_path), "critic": critic_meta},
    )


def resolve_parent_genome(
    exp: dict[str, Any],
    parent_id: str = "",
    store: Any = None,
) -> tuple[Path, str]:
    """
    Return (path, genome_id) for mutation parent.

    Order when parent_id set: elite registry → SQLite artifact_path → genomes/{id}.
    Default: active_genome.json → genomes/active → seed.
    """
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    pid = (parent_id or "").strip()
    if pid:
        from organism.elites import resolve_genome_dir

        return resolve_genome_dir(artifacts, pid, store=store)

    active_json = artifacts / "active_genome.json"
    if active_json.exists():
        data = json.loads(active_json.read_text(encoding="utf-8"))
        path = Path(data["path"])
        if path.exists():
            return path, str(data.get("genome_id", "g_active"))
    active_dir = artifacts / "genomes" / "active"
    if active_dir.exists() and (active_dir / "policy.py").exists():
        return active_dir, "g_active"
    seed_art = artifacts / "genomes" / "seed"
    if seed_art.exists() and (seed_art / "policy.py").exists():
        return seed_art, "g_seed"
    seed = resolve_path(exp.get("paths", {}).get("seed_genome", "genomes/seed"))
    return seed, "g_seed"
