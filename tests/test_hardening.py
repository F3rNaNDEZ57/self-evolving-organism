"""Unit tests for Phase 2 hardening (timeout, llm_calls, manifest, critic fail_open)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from organism.critic import review_proposal
from organism.manifest import build_manifest, write_manifest
from organism.nim_client import ChatResult
from organism.persistence import Store
from organism.validate import validate_source


def test_llm_calls_table_and_cost_rollup(tmp_path: Path):
    store = Store(tmp_path / "t.sqlite")
    store.insert_llm_call(
        model="test-model",
        role="coder",
        mutation_id="m_x",
        tokens_in=100,
        tokens_out=50,
        estimated_usd=0.0,
        latency_ms=12.5,
    )
    store.insert_llm_call(
        model="test-critic",
        role="critic",
        mutation_id="m_x",
        tokens_in=40,
        tokens_out=20,
        latency_ms=5.0,
    )
    usage = store.llm_usage_for_mutation("m_x")
    assert usage["calls"] == 2
    assert usage["tokens_total"] == 210
    cpag = store.cost_per_accepted_gain(
        parent_fitness=1.0, candidate_fitness=3.0, tokens_total=210
    )
    assert cpag == 210 / 2.0
    assert store.cost_per_accepted_gain(
        parent_fitness=3.0, candidate_fitness=1.0, tokens_total=210
    ) is None
    store.close()


def test_manifest_written(tmp_path: Path):
    from organism.config import ROOT

    m = build_manifest(
        run_id="test_run",
        run_kind="ablation",
        root=ROOT,
        exp={"eval": {"N": 8}},
        world={"T": 200},
        fitness={"delta_success": 0.3},
        nim_pins={"coder_primary": "deepseek-ai/deepseek-v4-flash"},
        rng_roots={"train_seeds": [0, 1]},
    )
    assert m["git_sha"]
    assert "python" in m
    assert m["nim_pins"]["coder_primary"]
    path = write_manifest(tmp_path / "manifest.json", m)
    assert path.exists()
    assert "test_run" in path.read_text(encoding="utf-8")


def test_critic_fail_closed_on_nim_error():
    client = MagicMock()
    client.cfg = {"models": {"critic": "x", "coder_fallback": "y", "coder_primary": "z"}}
    client.chat.side_effect = RuntimeError("NIM down")
    safe = {
        "policy.py": (
            "from organism.schemas import Action, Observation, StepResult\n"
            "class Policy:\n"
            "    def reset(self, seed): pass\n"
            "    def act(self, observation): return Action.NOOP\n"
            "    def on_step_result(self, result): pass\n"
        )
    }
    v = review_proposal(files=safe, rationale="t", client=client, dry_run=False, fail_open=False)
    assert not v.approved
    assert "fail_closed" in " ".join(v.reasons) or v.code == "other"


def test_critic_fail_open_on_nim_error():
    client = MagicMock()
    client.cfg = {"models": {"critic": "x", "coder_fallback": "y", "coder_primary": "z"}}
    client.chat.side_effect = RuntimeError("NIM down")
    safe = {
        "policy.py": (
            "from organism.schemas import Action, Observation, StepResult\n"
            "class Policy:\n"
            "    def reset(self, seed): pass\n"
            "    def act(self, observation): return Action.NOOP\n"
            "    def on_step_result(self, result): pass\n"
        )
    }
    v = review_proposal(files=safe, rationale="t", client=client, dry_run=False, fail_open=True)
    assert v.approved
    assert v.code == "fail_open"


def test_chat_result_shape():
    r = ChatResult(content="hi", model="m", tokens_in=1, tokens_out=2, latency_ms=3.0)
    d = r.to_dict()
    assert d["tokens_in"] == 1
    assert d["estimated_usd"] == 0.0


def test_bare_organism_import_denied():
    src = "import organism\nclass Policy:\n    def reset(self,s): pass\n    def act(self,o): pass\n    def on_step_result(self,r): pass\n"
    errs = validate_source("policy.py", src)
    assert any("forbidden" in e for e in errs)
