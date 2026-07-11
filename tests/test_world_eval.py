from organism.evaluator import FitnessConfig, evaluate, run_episode
from organism.genome_loader import make_policy_factory
from organism.weights import WeightConfig
from organism.world import WorldConfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "genomes" / "seed"


def test_episode_runs():
    world = WorldConfig(height=12, width=12, T=50, food_density=0.05)
    factory = make_policy_factory(SEED, ablation="B0")
    summary = run_episode(factory(), world, seed=0, train_weights=False)
    assert summary.ticks_survived > 0
    assert summary.ticks_survived <= 50


def test_eval_b0():
    world = WorldConfig(height=12, width=12, T=40, food_density=0.05)
    fit = FitnessConfig(T=40, energy_max=100)
    factory = make_policy_factory(SEED, ablation="B0", weight_cfg=WeightConfig())
    result = evaluate(factory, world, fit, seeds=[0, 1], train_weights=False)
    assert isinstance(result.fitness, float)
