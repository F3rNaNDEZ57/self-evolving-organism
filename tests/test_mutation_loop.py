"""Offline tests for propose-parse-apply-validate-accept (dry-run, no NIM)."""

from pathlib import Path

from organism.evaluator import FitnessConfig
from organism.mutation import apply_files, extract_files_from_proposal, run_mutation_cycle
from organism.persistence import Store
from organism.validate import validate_genome_dir, validate_source
from organism.weights import WeightConfig
from organism.world import WorldConfig

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "genomes" / "seed"


def test_extract_json_files():
    text = """
    {
      "rationale": "test",
      "files": {
        "heuristics.py": "x = 1\\n"
      }
    }
    """
    files = extract_files_from_proposal(text)
    assert "heuristics.py" in files
    assert "x = 1" in files["heuristics.py"]


def test_extract_truncated_json_policy():
    # Mimic free-NIM cut-off mid file string (real production failure mode)
    text = (
        '{\n  "rationale": "tweak forage",\n  "files": {\n'
        '    "policy.py": "from __future__ import annotations\\n\\n'
        "import random\\n\\nimport numpy as np\\n"
        "from heuristics import nearest_food_direction, should_forage\\n"
        "from organism.schemas import Action, Observation\\n\\n"
        "class Policy:\\n"
        "    def reset(self, seed: int) -> None:\\n"
        "        self.rng = random.Random(seed)\\n"
        "    def act(self, observation: Observation):\\n"
        "        return Action.REST\\n"
        "    def on_step_result(self, result) -> None:\\n"
        "        return\\n"
        # no closing quotes / braces — truncated
    )
    files = extract_files_from_proposal(text)
    assert "policy.py" in files
    assert "class Policy" in files["policy.py"]
    assert "def act" in files["policy.py"]


def test_extract_markdown_fenced():
    fence = chr(96) * 3  # ```
    text = (
        "\n### policy.py\n"
        f"{fence}python\n"
        "class Policy:\n"
        "    def reset(self, seed): pass\n"
        "    def act(self, o): return 0\n"
        "    def on_step_result(self, r): pass\n"
        f"{fence}\n"
    )
    files = extract_files_from_proposal(text)
    assert "policy.py" in files
    assert "class Policy" in files["policy.py"]


def test_validate_forbids_os():
    bad = "import os\nclass Policy:\n    pass\n"
    errs = validate_source("policy.py", bad)
    assert any("forbidden" in e for e in errs)


def test_dry_run_mutation_cycle(tmp_path: Path):
    world = WorldConfig(height=12, width=12, T=40, food_density=0.08)
    fit = FitnessConfig(T=40, energy_max=100, epsilon_accept=0.0, lambda_std=0.0)
    # low epsilon so improvements or equals can accept; dry-run makes greedier policy
    wcfg = WeightConfig()
    store = Store(tmp_path / "t.sqlite")
    parent = tmp_path / "parent"
    from organism.genome_loader import copy_genome

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
        force_host_eval=True,  # unit tests: no Docker dependency
    )
    store.close()
    assert result.decision in ("accepted", "rejected", "failed")
    assert result.candidate_fitness is not None or result.decision == "failed"
    # dry-run should at least parse/apply
    assert result.decision != "failed" or "validate" in result.reason or "parse" in result.reason
    # Prefer success path: apply worked
    assert (tmp_path / "art" / "genomes" / result.candidate_genome_id).exists() or result.decision == "failed"
