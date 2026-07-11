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
from organism.critic import CriticVerdict, review_proposal
from organism.evaluator import EvalResult, FitnessConfig, episode_score, evaluate, run_episode
from organism.genome_loader import WHITELIST, copy_genome, make_policy_factory
from organism.nim_client import NimClient
from organism.persistence import Store
from organism.validate import GenomeValidationError, assert_valid_genome, validate_genome_dir
from organism.weights import WeightConfig
from organism.world import WorldConfig

MUTATION_SYSTEM = """You are the mutation coder for a self-evolving digital organism on a 24x24 grid.
You may ONLY change whitelist modules: policy.py, heuristics.py, memory_hooks.py.

Rules:
- Improve food collection and survival.
- Do NOT import os, sys, subprocess, socket, pathlib, shutil, or use eval/exec/open.
- Allowed: random, math, typing, numpy, organism.schemas, organism.weights, and sibling modules.
- policy.py MUST define class Policy with methods: reset(seed), act(observation), on_step_result(result).
- Keep total changes small (prefer under 80 new/changed lines of logic).

Respond with ONLY a JSON object (no markdown fences) of this shape:
{
  "rationale": "one short paragraph",
  "files": {
    "heuristics.py": "full file source if changed, else omit key",
    "policy.py": "full file source if changed, else omit key",
    "memory_hooks.py": "full file source if changed, else omit key"
  }
}
Include at least one file. Provide COMPLETE file contents for each included key (not a diff).
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


def extract_files_from_proposal(text: str) -> dict[str, str]:
    """Parse LLM proposal into {filename: source}."""
    text = text.strip()
    # Strip markdown fences wrapping whole JSON
    fence = re.match(r"^```(?:json)?\s*([\s\S]*?)```\s*$", text)
    if fence:
        text = fence.group(1).strip()

    # Prefer JSON
    try:
        data = json.loads(text)
        files = data.get("files") or {}
        out = {}
        for k, v in files.items():
            name = Path(str(k)).name
            if name in WHITELIST and isinstance(v, str) and v.strip():
                out[name] = v
        if out:
            return out
    except json.JSONDecodeError:
        pass

    # Find JSON object substring
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
            files = data.get("files") or {}
            out = {}
            for k, v in files.items():
                name = Path(str(k)).name
                if name in WHITELIST and isinstance(v, str) and v.strip():
                    out[name] = v
            if out:
                return out
        except json.JSONDecodeError:
            pass

    # Markdown: ### file.py or **file.py** then ```python
    out = {}
    pattern = re.compile(
        r"(?:^|\n)(?:#{1,3}\s*|[*]{0,2})(policy|heuristics|memory_hooks)\.py(?:[*]{0,2})?\s*\n```(?:python)?\n([\s\S]*?)```",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        name = f"{m.group(1).lower()}.py"
        if name in WHITELIST:
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
        "Improve survival and food collection. Return JSON with full file sources for changed modules only.\n"
        "Keep Policy interface; only use real Observation fields (tick not ticks).\n"
        f"Recent episode summaries: {json.dumps(episode_summaries[:8])}\n\n"
        + "\n\n".join(sources)
    )
    chat_usage: dict[str, Any] | None = None
    if router is not None:
        rtr: FreeNimRouter = router
        chat = rtr.chat(
            "code",
            [
                {"role": "system", "content": MUTATION_SYSTEM},
                {"role": "user", "content": user},
            ],
            max_tokens=4096,
            temperature=0.2,
            fallback_role="coder_fallback",
        )
        text = chat.content
        model = chat.model
        chat_usage = chat.to_dict()
    else:
        model = client.cfg["models"]["coder_primary"]
        try:
            chat = client.chat(
                [
                    {"role": "system", "content": MUTATION_SYSTEM},
                    {"role": "user", "content": user},
                ],
                model=model,
                max_tokens=4096,
                temperature=0.2,
                role="coder",
            )
            text = chat.content
            chat_usage = chat.to_dict()
        except Exception:
            model = client.cfg["models"].get("coder_fallback", model)
            chat = client.chat(
                [
                    {"role": "system", "content": MUTATION_SYSTEM},
                    {"role": "user", "content": user},
                ],
                model=model,
                max_tokens=4096,
                temperature=0.2,
                role="coder_fallback",
            )
            text = chat.content
            chat_usage = chat.to_dict()
    if store is not None and chat_usage is not None:
        store.insert_llm_call(
            model=str(chat_usage.get("model", model)),
            role=str(chat_usage.get("role") or "coder"),
            mutation_id=mutation_id,
            tokens_in=chat_usage.get("tokens_in"),
            tokens_out=chat_usage.get("tokens_out"),
            estimated_usd=float(chat_usage.get("estimated_usd") or 0.0),
            latency_ms=float(chat_usage.get("latency_ms") or 0.0),
            meta={"stage": "propose"},
        )
    files = extract_files_from_proposal(text)
    return {
        "model": model,
        "proposal": text,
        "rationale": extract_rationale(text),
        "files": files,
        "applied": False,
        "llm_usage": chat_usage,
        "experience_distill": experience_distill,
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

    # 1) Parent fitness (host unless parent_isolation)
    parent_force_host = force_host_eval or not sb.parent_isolation
    parent_eval = _eval_genome(
        parent_dir,
        world,
        fit,
        wcfg,
        train_seeds,
        ablation,
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

    summaries = _episode_context(parent_dir, world, fit, wcfg, ablation, train_seeds)

    # 1b) Structured mutation memory (SQL lessons — no vectors)
    from organism.mutation_memory import format_lessons_for_prompt, retrieve_mutation_lessons
    from organism.router import FreeNimRouter
    from organism.summarizer import distill_episodes

    lessons = retrieve_mutation_lessons(store, k=5, parent_genome_id=parent_genome_id)
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

    if not files:
        reason = "apply/validate failed: could not parse any whitelist files from model proposal"
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
            files_changed=[],
            critic_decision="skipped",
        )

    # 2b) Critic before expensive apply/eval (static hard-fail + free NIM / dry-run)
    if use_critic:
        fail_open = bool(ccfg.get("fail_open", True))
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
            ablation,
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
            f"fitness {cand_eval.fitness:.4f} >= parent {parent_eval.fitness:.4f} + ε {epsilon}"
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
            f"fitness {cand_eval.fitness:.4f} < parent {parent_eval.fitness:.4f} + ε {epsilon}"
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


def resolve_parent_genome(exp: dict[str, Any]) -> tuple[Path, str]:
    """Return (path, genome_id) for current active or seed genome."""
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
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
