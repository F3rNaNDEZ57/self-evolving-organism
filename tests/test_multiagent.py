"""Multi-agent same-map Watch (viz only)."""

from pathlib import Path

from organism.genome_loader import copy_genome, make_policy_factory
from organism.multiagent import (
    multi_frame_to_rgb,
    multi_replay_to_gif,
    record_multi_episode,
    trails_up_to,
)
from organism.weights import WeightConfig
from organism.world import WorldConfig

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "genomes" / "seed"


def test_record_multi_episode(tmp_path: Path):
    g1 = tmp_path / "g1"
    g2 = tmp_path / "g2"
    copy_genome(SEED, g1)
    copy_genome(SEED, g2)
    world = WorldConfig(height=12, width=12, T=30, food_density=0.12, vision=2)
    wcfg = WeightConfig()
    policies = [
        (
            "g1",
            make_policy_factory(g1, ablation="Bc", weight_cfg=wcfg, force_train=False)(),
        ),
        (
            "g2",
            make_policy_factory(g2, ablation="B0", weight_cfg=wcfg, force_train=False)(),
        ),
    ]
    rep = record_multi_episode(
        policies, world, seed=0, ablation="Bc", episode_timeout_s=20.0
    )
    assert not rep.error
    assert len(rep.frames) >= 2
    assert len(rep.genome_ids) == 2
    assert len(rep.frames[0].agents) == 2
    rgb = multi_frame_to_rgb(rep.frames[-1], cell=4)
    assert rgb.shape[2] == 3
    trails = trails_up_to(rep.frames, len(rep.frames) - 1)
    assert len(trails) == 2
    out = multi_replay_to_gif(rep, tmp_path / "m.gif", cell=6, duration_ms=40)
    assert out.exists() and out.stat().st_size > 50
    assert any(a["food_collected"] >= 0 for a in rep.final)
