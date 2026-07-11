"""Episode replay / watch frames."""

from pathlib import Path

import numpy as np

from organism.evaluator import FitnessConfig
from organism.genome_loader import make_policy_factory
from organism.replay import frame_to_rgb, record_episode, replay_to_gif, trail_up_to
from organism.world import WorldConfig
from organism.weights import WeightConfig


ROOT = Path(__file__).resolve().parents[1]
SEED_GENOME = ROOT / "genomes" / "seed"


def test_record_episode_frames_in_bounds():
    world = WorldConfig(height=12, width=12, T=40, food_density=0.08)
    fit = FitnessConfig(T=40, energy_max=100.0)
    factory = make_policy_factory(
        SEED_GENOME,
        ablation="Bc",
        weight_cfg=WeightConfig(),
        force_train=False,
    )
    pol = factory()
    rep = record_episode(
        pol,
        world,
        seed=0,
        train_weights=False,
        episode_timeout_s=30.0,
        genome_id="g_seed",
        ablation="Bc",
        fit_cfg=fit,
    )
    assert not rep.error
    assert len(rep.frames) >= 2
    assert rep.frames[0].action is None
    h, w = world.height, world.width
    for fr in rep.frames:
        assert 0 <= fr.x < h
        assert 0 <= fr.y < w
        assert fr.food.shape == (h, w)
    rgb = frame_to_rgb(rep.frames[-1], cell=4)
    assert rgb.shape[2] == 3
    assert rgb.dtype == np.uint8
    trail = trail_up_to(rep.frames, len(rep.frames) - 1)
    assert (rep.frames[0].x, rep.frames[0].y) in trail


def test_replay_to_gif(tmp_path):
    world = WorldConfig(height=8, width=8, T=15, food_density=0.1)
    factory = make_policy_factory(
        SEED_GENOME,
        ablation="B0",
        weight_cfg=WeightConfig(),
        force_train=False,
    )
    rep = record_episode(factory(), world, seed=1, train_weights=False)
    out = replay_to_gif(rep, tmp_path / "ep.gif", cell=6, duration_ms=40)
    assert out.exists()
    assert out.stat().st_size > 50
