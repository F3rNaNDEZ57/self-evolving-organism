"""Docker episode isolation tests (skip if Docker unavailable)."""

from pathlib import Path

import pytest

from organism.config import ROOT
from organism.evaluator import FitnessConfig
from organism.genome_loader import copy_genome
from organism.sandbox import (
    SandboxConfig,
    build_sandbox_image,
    docker_available,
    evaluate_genome,
    evaluate_genome_in_docker,
    image_exists,
)
from organism.weights import WeightConfig
from organism.world import WorldConfig

SEED = ROOT / "genomes" / "seed"


@pytest.mark.skipif(not docker_available(), reason="Docker not available")
def test_docker_episode_eval(tmp_path: Path):
    image = "seo-sandbox:py312"
    if not image_exists(image):
        built = build_sandbox_image(image=image, context=ROOT)
        assert built["ok"], built.get("stderr_tail")

    genome = tmp_path / "g"
    copy_genome(SEED, genome)
    world = WorldConfig(height=10, width=10, T=20, food_density=0.1, vision=2)
    fit = FitnessConfig(T=20, energy_max=100, lambda_std=0.0)
    sb = SandboxConfig(image=image, episode_isolation=True, network="none", memory="512m", cpus="1")

    result = evaluate_genome_in_docker(
        genome,
        world=world,
        fit=fit,
        wcfg=WeightConfig(),
        seeds=[0, 1],
        ablation="Bc",
        cfg=sb,
        train_weights=False,
        project_root=ROOT,
    )
    assert isinstance(result.fitness, float)
    assert len(result.episodes) == 2
    assert result.seeds == [0, 1]


@pytest.mark.skipif(not docker_available(), reason="Docker not available")
def test_evaluate_genome_dispatch_docker(tmp_path: Path):
    image = "seo-sandbox:py312"
    if not image_exists(image):
        build_sandbox_image(image=image, context=ROOT)

    genome = tmp_path / "g"
    copy_genome(SEED, genome)
    world = WorldConfig(height=8, width=8, T=15, food_density=0.1, vision=2)
    fit = FitnessConfig(T=15, energy_max=100, lambda_std=0.0)
    sb = SandboxConfig(image=image, episode_isolation=True)

    r = evaluate_genome(
        genome,
        world=world,
        fit=fit,
        wcfg=WeightConfig(),
        seeds=[0],
        ablation="B0",
        sandbox=sb,
        force_docker=True,
    )
    assert len(r.episodes) == 1
