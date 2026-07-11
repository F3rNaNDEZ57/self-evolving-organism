"""Weight training diagnostics."""

from pathlib import Path

from organism.checkpoints import train_and_checkpoint
from organism.evaluator import FitnessConfig
from organism.genome_loader import copy_genome
from organism.weights import WeightConfig
from organism.weights_diagnose import diagnose_weights
from organism.world import WorldConfig

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "genomes" / "seed"


def test_diagnose_writes_report(tmp_path: Path):
    art = tmp_path / "art"
    art.mkdir()
    g = art / "g"
    copy_genome(SEED, g)
    world = WorldConfig(height=10, width=10, T=25, food_density=0.1, vision=2)
    fit = FitnessConfig(T=25, energy_max=100, epsilon_accept=0.0, lambda_std=0.0)
    wcfg = WeightConfig()
    meta = train_and_checkpoint(
        genome_dir=g,
        world=world,
        wcfg=wcfg,
        train_seeds=[0, 1],
        artifacts_dir=art,
        genome_id="g",
        passes=1,
        fit_cfg=fit,
        eval_seeds=[0, 1],
    )
    rep = diagnose_weights(
        genome_dir=g,
        genome_id="g",
        world=world,
        fit=fit,
        wcfg=wcfg,
        train_seeds=[0, 1],
        holdout_seeds=[2, 3],
        weight_path=Path(meta.path),
        artifacts_dir=art,
        margin=0.05,
    )
    assert (art / "last_weights_diagnose.json").exists()
    assert rep.recommendation
    assert isinstance(rep.recommend_use_weights, bool)
