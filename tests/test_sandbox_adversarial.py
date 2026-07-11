"""Adversarial containment tests — Phase 2 exit criterion (zero host escape smoke)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from organism.config import ROOT
from organism.evaluator import FitnessConfig, run_episode
from organism.genome_loader import copy_genome, load_policy_class
from organism.sandbox import (
    SandboxConfig,
    build_sandbox_image,
    docker_available,
    evaluate_genome_in_docker,
    image_exists,
    outer_eval_timeout_s,
    run_python_in_docker,
    smoke_network_block,
)
from organism.validate import validate_source
from organism.weights import WeightConfig
from organism.world import WorldConfig

SEED = ROOT / "genomes" / "seed"


# ---------------------------------------------------------------------------
# 1.1 / static validation — kernel and dangerous imports rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source,needle",
    [
        ("import os\nclass Policy:\n    def reset(self,s): pass\n    def act(self,o): pass\n    def on_step_result(self,r): pass\n", "forbidden"),
        ("import subprocess\nclass Policy:\n    def reset(self,s): pass\n    def act(self,o): pass\n    def on_step_result(self,r): pass\n", "forbidden"),
        ("import socket\nclass Policy:\n    def reset(self,s): pass\n    def act(self,o): pass\n    def on_step_result(self,r): pass\n", "forbidden"),
        (
            "from organism.config import nim_config\nclass Policy:\n    def reset(self,s): pass\n    def act(self,o): pass\n    def on_step_result(self,r): pass\n",
            "forbidden",
        ),
        (
            "from organism.sandbox import evaluate_genome\nclass Policy:\n    def reset(self,s): pass\n    def act(self,o): pass\n    def on_step_result(self,r): pass\n",
            "forbidden",
        ),
        (
            "from organism.nim_client import NimClient\nclass Policy:\n    def reset(self,s): pass\n    def act(self,o): pass\n    def on_step_result(self,r): pass\n",
            "forbidden",
        ),
        (
            "import organism.persistence\nclass Policy:\n    def reset(self,s): pass\n    def act(self,o): pass\n    def on_step_result(self,r): pass\n",
            "forbidden",
        ),
    ],
)
def test_validate_rejects_hostile_imports(source: str, needle: str):
    errs = validate_source("policy.py", source)
    assert errs, "expected validation errors"
    assert any(needle in e for e in errs)


def test_validate_allows_facade_and_schemas():
    ok = textwrap.dedent(
        """
        from organism.schemas import Action, Observation, StepResult
        from organism.weights import LinearScorer, WeightConfig
        from organism.organism_api import Action as A2

        class Policy:
            def reset(self, seed): pass
            def act(self, observation):
                return Action.NOOP
            def on_step_result(self, result): pass
        """
    )
    assert validate_source("policy.py", ok) == []


def test_seed_genome_still_validates():
    from organism.validate import validate_genome_dir

    assert validate_genome_dir(SEED) == []


# ---------------------------------------------------------------------------
# 2.1 wall-clock episode timeout (host)
# ---------------------------------------------------------------------------


def test_episode_wall_timeout_scores_zero():
    class SlowPolicy:
        def reset(self, seed): pass
        def act(self, obs):
            import time
            time.sleep(0.05)
            from organism.schemas import Action
            return Action.NOOP
        def on_step_result(self, r): pass

    world = WorldConfig(height=8, width=8, T=200, food_density=0.1)
    ep = run_episode(SlowPolicy(), world, seed=0, episode_timeout_s=0.1)
    assert ep.death_reason == "timeout_wall"
    from organism.evaluator import episode_score, FitnessConfig
    score = episode_score(ep, FitnessConfig(T=200))
    assert score == 0.0


# ---------------------------------------------------------------------------
# Docker adversarial cases
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not docker_available(), reason="Docker not available")
def test_docker_network_blocked():
    r = smoke_network_block()
    assert r["ok"], r.get("output")
    assert "NETWORK_LEAK" not in r.get("output", "")


@pytest.mark.skipif(not docker_available(), reason="Docker not available")
def test_docker_readonly_root_blocks_host_write():
    """Writing outside /tmp under --read-only must fail."""
    cfg = SandboxConfig(image="python:3.12-slim", network="none")
    code = (
        "import sys\n"
        "try:\n"
        "  open('/etc/seo_escape','w').write('x')\n"
        "  print('WRITE_LEAK')\n"
        "except Exception as e:\n"
        "  print('write_blocked', type(e).__name__)\n"
        "print('ro_pass')\n"
    )
    proc = run_python_in_docker(code, cfg=cfg, timeout_s=60)
    out = (proc.stdout or "") + (proc.stderr or "")
    assert "WRITE_LEAK" not in out
    assert "ro_pass" in out or "write_blocked" in out


@pytest.mark.skipif(not docker_available(), reason="Docker not available")
def test_docker_infinite_loop_killed_by_outer_timeout(tmp_path: Path):
    """Hostile act() loop: outer docker timeout (derived from episode budget) must kill."""
    image = "seo-sandbox:py312"
    if not image_exists(image):
        built = build_sandbox_image(image=image, context=ROOT)
        assert built["ok"], built.get("stderr_tail")

    genome = tmp_path / "g"
    copy_genome(SEED, genome)
    # Replace policy with infinite loop in act
    (genome / "policy.py").write_text(
        textwrap.dedent(
            """
            from organism.schemas import Action, Observation, StepResult

            class Policy:
                def reset(self, seed): pass
                def act(self, observation):
                    while True:
                        pass
                    return Action.NOOP
                def on_step_result(self, result): pass
            """
        ),
        encoding="utf-8",
    )
    # Note: infinite loop fails static? No — validate allows while True.
    # AST does not forbid infinite loops; Docker outer timeout is the backstop.
    world = WorldConfig(height=6, width=6, T=10, food_density=0.1)
    fit = FitnessConfig(T=10, energy_max=100, lambda_std=0.0, episode_timeout_s=1.0)
    sb = SandboxConfig(image=image, episode_isolation=True, episode_timeout_s=1.0)
    # Outer timeout should be short: 1 seed * 1s * 1.5 + 15 ≈ 16.5 → max(30, ...) = 30
    # Force smaller via timeout_s for test speed
    import subprocess
    from organism.sandbox import evaluate_genome_in_docker as eg

    with pytest.raises((RuntimeError, subprocess.TimeoutExpired, Exception)):
        evaluate_genome_in_docker(
            genome,
            world=world,
            fit=fit,
            wcfg=WeightConfig(),
            seeds=[0],
            ablation="Bc",
            cfg=sb,
            train_weights=False,
            timeout_s=8,  # hard kill
            episode_timeout_s=1.0,
            project_root=ROOT,
        )


@pytest.mark.skipif(not docker_available(), reason="Docker not available")
def test_docker_eval_seed_still_works_after_hardening(tmp_path: Path):
    image = "seo-sandbox:py312"
    if not image_exists(image):
        built = build_sandbox_image(image=image, context=ROOT)
        assert built["ok"], built.get("stderr_tail")

    genome = tmp_path / "g"
    copy_genome(SEED, genome)
    world = WorldConfig(height=10, width=10, T=20, food_density=0.1)
    fit = FitnessConfig(T=20, energy_max=100, lambda_std=0.0, episode_timeout_s=5.0)
    sb = SandboxConfig(image=image, episode_isolation=True)
    result = evaluate_genome_in_docker(
        genome,
        world=world,
        fit=fit,
        wcfg=WeightConfig(),
        seeds=[0],
        ablation="Bc",
        cfg=sb,
        project_root=ROOT,
    )
    assert isinstance(result.fitness, float)


def test_outer_timeout_scales_with_seeds():
    assert outer_eval_timeout_s(8, 5.0) >= 8 * 5 * 1.5
    assert outer_eval_timeout_s(1, 1.0) >= 30


# ---------------------------------------------------------------------------
# 4.1 genome_loader cleanup
# ---------------------------------------------------------------------------


def test_load_policy_does_not_leave_bare_aliases(tmp_path: Path):
    import sys

    g1 = tmp_path / "g1"
    g2 = tmp_path / "g2"
    copy_genome(SEED, g1)
    copy_genome(SEED, g2)
    (g2 / "heuristics.py").write_text(
        (g1 / "heuristics.py").read_text(encoding="utf-8") + "\nMARKER_G2 = True\n",
        encoding="utf-8",
    )
    P1 = load_policy_class(g1)
    assert "heuristics" not in sys.modules or not str(
        getattr(sys.modules.get("heuristics"), "__file__", "")
    ).startswith(str(g1.resolve()))
    P2 = load_policy_class(g2)
    assert P1 is not P2
    # factories still construct
    assert P1() is not None
    assert P2() is not None
