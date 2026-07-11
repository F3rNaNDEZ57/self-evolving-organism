from pathlib import Path

import numpy as np

from organism.checkpoints import (
    list_checkpoints,
    load_scorer,
    resolve_checkpoint_path,
    save_checkpoint,
    train_and_checkpoint,
)
from organism.evaluator import FitnessConfig
from organism.genome_loader import copy_genome
from organism.weights import LinearScorer, WeightConfig
from organism.world import WorldConfig

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "genomes" / "seed"


def test_save_load_roundtrip(tmp_path: Path):
    cfg = WeightConfig()
    scorer = LinearScorer(27, cfg, rng=np.random.default_rng(0))
    scorer.theta += 0.5
    scorer.baseline = 1.25
    meta = save_checkpoint(
        scorer,
        artifacts_dir=tmp_path,
        genome_id="g_test",
        label="unit",
        train_fitness=1.0,
        episodes_trained=3,
        weight_cfg=cfg,
    )
    assert Path(meta.path).exists()
    side = Path(meta.path).with_suffix(".json")
    assert side.exists()
    loaded, meta2 = load_scorer(meta.path, cfg)
    assert loaded.theta.shape == scorer.theta.shape
    assert np.allclose(loaded.theta, scorer.theta)
    assert abs(loaded.baseline - 1.25) < 1e-9
    assert meta2 is not None
    assert meta2.checkpoint_id == meta.checkpoint_id
    latest = resolve_checkpoint_path(tmp_path, "latest")
    assert latest.exists()
    assert list_checkpoints(tmp_path)


def test_train_and_checkpoint(tmp_path: Path):
    seed_dir = tmp_path / "seed"
    copy_genome(SEED, seed_dir)
    world = WorldConfig(height=10, width=10, T=20, food_density=0.1, vision=2)
    fit = FitnessConfig(T=20, energy_max=100, lambda_std=0.0)
    meta = train_and_checkpoint(
        genome_dir=seed_dir,
        world=world,
        wcfg=WeightConfig(),
        train_seeds=[0, 1],
        artifacts_dir=tmp_path,
        genome_id="g_train",
        passes=1,
        fit_cfg=fit,
        eval_seeds=[0, 1],
    )
    assert Path(meta.path).exists()
    assert meta.episodes_trained >= 2
    assert meta.feature_dim > 0
