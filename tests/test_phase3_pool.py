"""Phase 3 pool: router, summarizer, metrics, critic A/B."""

from __future__ import annotations

from pathlib import Path

from organism.metrics import collect_pool_metrics, run_critic_ab, write_metrics_report
from organism.persistence import Store
from organism.router import BudgetState, FreeNimRouter
from organism.summarizer import distill_episodes_offline, format_distill_for_prompt


def test_router_role_pins():
    cfg = {
        "api_key": "x",
        "base_url": "https://example.invalid/v1",
        "max_rpm": 40,
        "models": {
            "coder_primary": "deepseek-ai/deepseek-v4-flash",
            "coder_fallback": "nvidia/nemotron-3-nano-30b-a3b",
            "critic": "nvidia/nemotron-3-nano-30b-a3b",
            "summarizer": "meta/llama-3.1-8b-instruct",
        },
        "budget": {"max_tokens_session": 1000, "max_calls_session": 5, "max_mutations": 2},
    }
    r = FreeNimRouter(cfg)
    assert "deepseek" in r.model_for("code")
    assert "nemotron" in r.model_for("critique")
    assert "llama" in r.model_for("summarize")
    assert r.budget.can_call()
    assert r.budget.can_mutate()
    from organism.nim_client import ChatResult

    r.budget.record(ChatResult(content="x", model="m", tokens_in=10, tokens_out=5, role="code"))
    assert r.budget.tokens_used == 15
    assert r.budget.calls_used == 1
    r.budget.record_mutation()
    assert r.budget.mutations_used == 1


def test_budget_exhaustion():
    b = BudgetState(max_tokens_session=10, max_calls_session=2)
    from organism.nim_client import ChatResult

    b.record(ChatResult(content="", model="m", tokens_in=6, tokens_out=4, role="code"))
    assert not b.can_call(estimated_tokens=1)
    b2 = BudgetState(max_calls_session=1)
    b2.record(ChatResult(content="", model="m", tokens_in=0, tokens_out=0, role="x"))
    assert not b2.can_call()


def test_offline_summarizer():
    eps = [
        {"seed": 0, "food": 0, "score": 1.0, "death": "energy"},
        {"seed": 1, "food": 0, "score": 0.5, "death": "energy"},
    ]
    d = distill_episodes_offline(eps)
    assert d["dry_run"] is True
    assert d["bullets"]
    assert "energy" in d["failure_modes"]
    txt = format_distill_for_prompt(d)
    assert "Experience" in txt or "bullets" in txt.lower() or "food" in txt.lower()


def test_metrics_rollup(tmp_path: Path):
    store = Store(tmp_path / "m.sqlite")
    store.insert_mutation(
        "m1",
        "g0",
        "g1",
        "rejected",
        "critic reject [unsafe_import]: forbidden",
        {
            "parent_fitness": 1.0,
            "candidate_fitness": None,
            "critic": {"decision": "reject", "code": "unsafe_import"},
        },
    )
    store.insert_mutation(
        "m2",
        "g0",
        "g2",
        "accepted",
        "fitness ok",
        {
            "parent_fitness": 1.0,
            "candidate_fitness": 3.0,
            "critic": {"decision": "approve", "code": "approve"},
        },
    )
    store.insert_llm_call(model="m", role="coder", mutation_id="m2", tokens_in=100, tokens_out=50)
    m = collect_pool_metrics(store)
    store.close()
    assert m.mutations_total == 2
    assert m.mutations_accepted == 1
    assert m.critic_rejects == 1
    assert m.evals_avoided_by_critic == 1
    assert m.tokens_total == 150
    assert m.tokens_per_accepted_gain is not None
    path = write_metrics_report(m, tmp_path / "out.json")
    assert path.exists()


def test_critic_ab_saves_evals():
    safe = {
        "rationale": "ok",
        "files": {
            "policy.py": (
                "from organism.schemas import Action, Observation, StepResult\n"
                "class Policy:\n"
                "    def reset(self, seed): pass\n"
                "    def act(self, observation): return Action.NOOP\n"
                "    def on_step_result(self, result): pass\n"
            )
        },
    }
    bad = {
        "rationale": "hack",
        "files": {
            "policy.py": "import os\nclass Policy:\n    def reset(self,s): pass\n"
            "    def act(self,o): pass\n    def on_step_result(self,r): pass\n"
        },
    }
    report = run_critic_ab([safe, bad, bad], parent_fitness=1.0)
    assert report.n_proposals == 3
    assert report.evals_saved >= 2
    assert report.with_critic_evals == report.n_proposals - report.critic_rejects
    assert report.without_critic_evals == 3
    assert report.critic_reject_rate > 0
