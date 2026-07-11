"""Dual-timescale best-of phenotype at evaluate_genome."""

from pathlib import Path

from organism.checkpoints import train_and_checkpoint
from organism.evaluator import FitnessConfig
from organism.genome_loader import copy_genome
from organism.sandbox import evaluate_genome
from organism.weights import WeightConfig
from organism.world import WorldConfig

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "genomes" / "seed"


def test_best_of_picks_code_when_weights_worse(tmp_path: Path):
    art = tmp_path / "art"
    art.mkdir()
    gdir = art / "g"
    copy_genome(SEED, gdir)
    world = WorldConfig(height=10, width=10, T=30, food_density=0.1, vision=2)
    fit = FitnessConfig(T=30, energy_max=100, epsilon_accept=0.0, lambda_std=0.0)
    wcfg = WeightConfig()
    meta = train_and_checkpoint(
        genome_dir=gdir,
        world=world,
        wcfg=wcfg,
        train_seeds=[0, 1],
        artifacts_dir=art,
        genome_id="g",
        passes=1,
        ablation="Bw",
        label="t",
        fit_cfg=fit,
        eval_seeds=[0, 1],
    )
    seeds = [0, 1, 2]
    raw_b0 = evaluate_genome(
        gdir,
        world=world,
        fit=fit,
        wcfg=wcfg,
        seeds=seeds,
        ablation="B0",
        train_weights=False,
        force_host=True,
        best_of_phenotype=False,
    )
    raw_bw = evaluate_genome(
        gdir,
        world=world,
        fit=fit,
        wcfg=wcfg,
        seeds=seeds,
        ablation="Bw",
        train_weights=False,
        weight_path=Path(meta.path),
        force_host=True,
        best_of_phenotype=False,
    )
    best = evaluate_genome(
        gdir,
        world=world,
        fit=fit,
        wcfg=wcfg,
        seeds=seeds,
        ablation="Bw",
        train_weights=False,
        weight_path=Path(meta.path),
        force_host=True,
        best_of_phenotype=True,
    )
    assert best.fitness_code_only is not None
    assert best.fitness_with_weights is not None
    assert abs(best.fitness - max(raw_b0.fitness, raw_bw.fitness)) < 1e-6
    assert best.phenotype in ("code_only", "with_weights")
    if raw_b0.fitness >= raw_bw.fitness:
        assert best.phenotype == "code_only"
    else:
        assert best.phenotype == "with_weights"
