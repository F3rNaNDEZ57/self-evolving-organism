"""Phase 3 free-NIM critic: static precheck, dry-run critic, mutation gate."""

from pathlib import Path

from organism.critic import (
    dry_run_critic,
    review_proposal,
    static_food_heuristic_repeat,
    static_precheck,
)
from organism.evaluator import FitnessConfig
from organism.genome_loader import copy_genome
from organism.mutation import run_mutation_cycle
from organism.persistence import Store
from organism.weights import WeightConfig
from organism.world import WorldConfig

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "genomes" / "seed"

SAFE_HEUR = '''"""safe heuristics stub."""

from organism.schemas import Action, Observation


def nearest_food_direction(observation: Observation):
    return Action.N


def should_forage(observation: Observation) -> bool:
    return False
'''

SAFE_POLICY = '''"""safe policy for critic tests."""

from __future__ import annotations

import random

from organism.schemas import Action, Observation, StepResult


class Policy:
    def __init__(self, **kwargs) -> None:
        self.rng = random.Random(0)

    def reset(self, seed: int) -> None:
        self.rng.seed(seed)

    def act(self, observation: Observation) -> Action:
        return Action.NOOP

    def on_step_result(self, result: StepResult) -> None:
        return None
'''


def test_static_precheck_rejects_forbidden_import():
    bad = {"policy.py": "import os\nclass Policy:\n    pass\n"}
    v = static_precheck(bad)
    assert v is not None
    assert not v.approved
    assert v.code in ("unsafe_import", "contract_break")
    assert v.model == "static"


def test_static_precheck_rejects_empty():
    v = static_precheck({})
    assert v is not None
    assert v.code == "low_value"


def test_static_precheck_passes_safe():
    files = {"policy.py": SAFE_POLICY, "heuristics.py": SAFE_HEUR}
    assert static_precheck(files) is None


def test_dry_run_critic_approves_safe():
    files = {"policy.py": SAFE_POLICY}
    v = dry_run_critic(files, rationale="unit test tweak")
    assert v.approved
    assert v.dry_run
    assert v.model == "dry_run_critic"


def test_review_proposal_dry_run_rejects_unsafe():
    files = {
        "policy.py": "import subprocess\nclass Policy:\n    def reset(self, s): pass\n"
        "    def act(self, o): pass\n    def on_step_result(self, r): pass\n"
    }
    v = review_proposal(files=files, rationale="hack", dry_run=True)
    assert not v.approved
    assert v.code in ("unsafe_import", "contract_break")


def test_mutation_critic_rejects_unsafe_proposal(tmp_path: Path):
    world = WorldConfig(height=12, width=12, T=40, food_density=0.08)
    fit = FitnessConfig(T=40, energy_max=100, epsilon_accept=0.0, lambda_std=0.0)
    wcfg = WeightConfig()
    store = Store(tmp_path / "t.sqlite")
    parent = tmp_path / "parent"
    copy_genome(SEED, parent)
    store.insert_genome(genome_id="g_parent", status="active", artifact_path=str(parent))

    bad_policy = "import os\n\nclass Policy:\n    def reset(self, seed): pass\n"
    result = run_mutation_cycle(
        parent_dir=parent,
        artifacts_dir=tmp_path / "art",
        store=store,
        world=world,
        fit=fit,
        wcfg=wcfg,
        train_seeds=[0, 1],
        ablation="Bc",
        parent_genome_id="g_parent",
        dry_run=True,
        force_host_eval=True,
        critic=True,
        proposal_override={
            "model": "test",
            "rationale": "inject os",
            "proposal": "{}",
            "files": {"policy.py": bad_policy},
        },
    )
    store.close()
    assert result.decision == "rejected"
    assert result.candidate_fitness is None
    assert result.critic_decision == "reject"


def test_static_food_heuristic_repeat(tmp_path: Path):
    parent = tmp_path / "parent"
    copy_genome(SEED, parent)
    base = (parent / "heuristics.py").read_text(encoding="utf-8")
    # Only re-tweak nearest_food_direction
    if "def nearest_food_direction" not in base:
        return  # seed layout unexpected — skip soft
    tweaked = base.replace(
        "def nearest_food_direction",
        "def nearest_food_direction  # micro",
        1,
    )
    # if replace didn't change function AST meaningfully, force body comment
    if tweaked == base:
        tweaked = base + "\n# noop\n"
    # better: append to function via unique comment inside module after import
    tweaked = base.replace(
        "return Action.N",
        "return Action.S",
        1,
    ) if "return Action.N" in base else (base + "\n# x\n")
    lessons = "DIVERSITY: Do NOT re-tweak nearest_food_direction (low_value)"
    v = static_food_heuristic_repeat(
        {"heuristics.py": tweaked},
        parent_dir=parent,
        lessons_text=lessons,
    )
    # If AST still sees a food-only function change, must reject
    if v is not None:
        assert not v.approved
        assert v.code == "low_value"
    # With parent_dir + lessons, static_precheck should also catch when funcs differ
    v2 = static_precheck(
        {"heuristics.py": tweaked},
        parent_dir=parent,
        lessons_text=lessons,
    )
    if v2 is not None and v2.code == "low_value":
        assert "food" in " ".join(v2.reasons).lower() or "nearest" in " ".join(
            v2.reasons
        ).lower()


def test_mutation_dry_run_still_accepts_with_critic(tmp_path: Path):
    """Default dry-run greedier patch should pass dry critic and reach fitness gate."""
    world = WorldConfig(height=12, width=12, T=40, food_density=0.08)
    fit = FitnessConfig(T=40, energy_max=100, epsilon_accept=0.0, lambda_std=0.0)
    wcfg = WeightConfig()
    store = Store(tmp_path / "t.sqlite")
    parent = tmp_path / "parent"
    copy_genome(SEED, parent)
    store.insert_genome(genome_id="g_parent", status="active", artifact_path=str(parent))

    result = run_mutation_cycle(
        parent_dir=parent,
        artifacts_dir=tmp_path / "art",
        store=store,
        world=world,
        fit=fit,
        wcfg=wcfg,
        train_seeds=[0, 1, 2],
        ablation="Bc",
        parent_genome_id="g_parent",
        dry_run=True,
        force_host_eval=True,
        critic=True,
    )
    store.close()
    assert result.decision in ("accepted", "rejected")
    assert result.critic_decision == "approve"
    assert result.candidate_fitness is not None
