from pathlib import Path

from organism.ablations import run_ablation_suite
from organism.config import experiment_config
from organism.evaluator import FitnessConfig
from organism.genome_loader import copy_genome
from organism.persistence import Store
from organism.weights import WeightConfig
from organism.world import WorldConfig

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "genomes" / "seed"


def test_quick_ablation_suite(tmp_path: Path):
    exp = experiment_config()
    # shrink world for speed
    world = WorldConfig(height=12, width=12, T=30, food_density=0.08, vision=2)
    fit = FitnessConfig(
        T=30,
        energy_max=100,
        epsilon_accept=0.0,
        delta_success=0.0,
        lambda_std=0.0,
    )
    wcfg = WeightConfig()
    store = Store(tmp_path / "a.sqlite")
    seed_dir = tmp_path / "seed"
    copy_genome(SEED, seed_dir)

    report = run_ablation_suite(
        exp=exp,
        world=world,
        fit=fit,
        wcfg=wcfg,
        store=store,
        artifacts_dir=tmp_path / "art",
        seed_dir=seed_dir,
        quick=True,
        dry_run=True,
        arms=["B0", "Bw", "Bc", "Bcw"],
        max_mutations=1,
    )
    store.close()
    assert set(report.arms.keys()) == {"B0", "Bw", "Bc", "Bcw"}
    assert "holdout_Bcw_minus_B0" in report.comparisons or report.delta_holdout_bcw_minus_b0 == (
        report.arms["Bcw"].holdout_fitness - report.arms["B0"].holdout_fitness
    )
    assert (tmp_path / "art" / "last_ablation_report.json").exists()
