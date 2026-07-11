"""Phase 3 metrics: critic quality, token cost, wasted-eval avoidance."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from organism.persistence import Store


@dataclass
class PoolMetrics:
    """Rollup over mutations (+ llm_calls) for a DB / time window."""

    mutations_total: int = 0
    mutations_accepted: int = 0
    mutations_rejected: int = 0
    mutations_failed: int = 0
    critic_rejects: int = 0
    critic_approves: int = 0
    critic_fail_open: int = 0
    critic_skipped: int = 0
    fitness_rejects: int = 0  # rejected after eval (not critic)
    evals_run: int = 0  # candidates that reached fitness eval
    evals_avoided_by_critic: int = 0
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_total: int = 0
    latency_ms: float = 0.0
    accepted_fitness_gains: list[float] = field(default_factory=list)
    tokens_per_accepted_gain: float | None = None
    accept_rate: float = 0.0
    critic_reject_rate: float = 0.0
    waste_avoidance_rate: float = 0.0  # critic_rejects / proposals_with_files
    by_role_tokens: dict[str, int] = field(default_factory=dict)
    by_critic_code: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def collect_pool_metrics(store: Store) -> PoolMetrics:
    """Aggregate mutation + llm_call rows from SQLite."""
    m = PoolMetrics()
    rows = store.conn.execute("SELECT decision, reason, meta_json FROM mutations").fetchall()
    for r in rows:
        decision = str(r["decision"] or "")
        reason = str(r["reason"] or "")
        try:
            meta = json.loads(r["meta_json"] or "{}")
        except json.JSONDecodeError:
            meta = {}
        m.mutations_total += 1
        if decision == "accepted":
            m.mutations_accepted += 1
            pf = meta.get("parent_fitness")
            cf = meta.get("candidate_fitness")
            if pf is not None and cf is not None:
                m.accepted_fitness_gains.append(float(cf) - float(pf))
        elif decision == "rejected":
            m.mutations_rejected += 1
        elif decision == "failed":
            m.mutations_failed += 1

        critic = meta.get("critic") or {}
        c_dec = str(critic.get("decision") or "")
        c_code = str(critic.get("code") or "")
        if c_code == "fail_open" or "fail_open" in reason:
            m.critic_fail_open += 1
        if c_dec == "reject" or reason.startswith("critic reject"):
            m.critic_rejects += 1
            m.evals_avoided_by_critic += 1
            code = c_code or "other"
            m.by_critic_code[code] = m.by_critic_code.get(code, 0) + 1
        elif c_dec == "approve":
            m.critic_approves += 1
            if decision in ("accepted", "rejected", "failed") and not reason.startswith("critic"):
                # reached post-critic path; fitness eval likely ran if candidate_fitness set
                if meta.get("candidate_fitness") is not None:
                    m.evals_run += 1
                if decision == "rejected" and not reason.startswith("critic"):
                    m.fitness_rejects += 1
        elif c_dec in ("", "skipped") and meta.get("candidate_fitness") is not None:
            m.critic_skipped += 1
            m.evals_run += 1
            if decision == "rejected":
                m.fitness_rejects += 1
        elif meta.get("candidate_fitness") is not None:
            m.evals_run += 1

    llm = store.conn.execute(
        "SELECT role, tokens_in, tokens_out, latency_ms FROM llm_calls"
    ).fetchall()
    for r in llm:
        m.llm_calls += 1
        tin = int(r["tokens_in"] or 0)
        tout = int(r["tokens_out"] or 0)
        m.tokens_in += tin
        m.tokens_out += tout
        m.tokens_total += tin + tout
        m.latency_ms += float(r["latency_ms"] or 0)
        role = str(r["role"] or "other")
        m.by_role_tokens[role] = m.by_role_tokens.get(role, 0) + tin + tout

    if m.mutations_total:
        m.accept_rate = m.mutations_accepted / m.mutations_total
    gated = m.critic_approves + m.critic_rejects
    if gated:
        m.critic_reject_rate = m.critic_rejects / gated
        m.waste_avoidance_rate = m.critic_rejects / gated
    total_gain = sum(g for g in m.accepted_fitness_gains if g > 0)
    if total_gain > 0 and m.tokens_total > 0:
        m.tokens_per_accepted_gain = m.tokens_total / total_gain
    return m


@dataclass
class CriticABReport:
    """Compare proposals with critic on vs off (offline / dry proposals)."""

    n_proposals: int
    with_critic_evals: int
    without_critic_evals: int
    critic_rejects: int
    static_rejects: int
    evals_saved: int
    critic_reject_rate: float
    notes: str = ""
    taxonomy: dict[str, int] = field(default_factory=dict)
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_critic_ab(
    proposals: list[dict[str, Any]],
    *,
    parent_fitness: float = 0.0,
) -> CriticABReport:
    """
    A/B: for each proposal {files, rationale}, count evals with critic gate vs always-eval.
    Offline — uses static + dry_run critic only (no live NIM required).
    """
    from organism.critic import review_proposal

    n = len(proposals)
    critic_rejects = 0
    static_rejects = 0
    taxonomy: dict[str, int] = {}
    for p in proposals:
        files = p.get("files") or {}
        rationale = str(p.get("rationale") or "")
        v = review_proposal(
            files=files,
            rationale=rationale,
            parent_fitness=parent_fitness,
            dry_run=True,
            fail_open=True,
        )
        if not v.approved:
            critic_rejects += 1
            taxonomy[v.code] = taxonomy.get(v.code, 0) + 1
            if v.model == "static":
                static_rejects += 1
    with_critic_evals = n - critic_rejects
    without = n  # always eval
    return CriticABReport(
        n_proposals=n,
        with_critic_evals=with_critic_evals,
        without_critic_evals=without,
        critic_rejects=critic_rejects,
        static_rejects=static_rejects,
        evals_saved=critic_rejects,
        critic_reject_rate=(critic_rejects / n) if n else 0.0,
        notes="dry_run critic A/B - live NIM critic may differ",
        taxonomy=taxonomy,
        created_at=time.time(),
    )


def write_metrics_report(
    metrics: PoolMetrics,
    path: Path,
    *,
    extra: dict[str, Any] | None = None,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": time.time(),
        "metrics": metrics.to_dict(),
        "extra": extra or {},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
