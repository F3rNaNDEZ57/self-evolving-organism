from pathlib import Path

from organism.evolve import EvolveConfig, detect_trigger, run_evolve
from organism.evaluator import FitnessConfig
from organism.genome_loader import copy_genome
from organism.persistence import Store
from organism.weights import WeightConfig
from organism.world import WorldConfig

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "genomes" / "seed"


def test_detect_schedule():
    cfg = EvolveConfig(mutate_every_episodes=10, plateau_episodes=100)
    fire, reason = detect_trigger(
        episodes_since_mutation=10,
        fitness_history=[1.0, 1.1],
        cfg=cfg,
    )
    assert fire and reason == "schedule"


def test_detect_plateau():
    cfg = EvolveConfig(mutate_every_episodes=1000, plateau_episodes=3, plateau_epsilon=0.05)
    hist = [1.0, 1.01, 1.0, 1.02, 1.01, 0.99]
    fire, reason = detect_trigger(
        episodes_since_mutation=1,
        fitness_history=hist,
        cfg=cfg,
    )
    assert fire and reason == "plateau"


def test_run_evolve_dry(tmp_path: Path):
    seed_dir = tmp_path / "seed"
    copy_genome(SEED, seed_dir)
    # point active genome at seed
    art = tmp_path / "art"
    art.mkdir()
    (art / "genomes").mkdir()
    copy_genome(SEED, art / "genomes" / "seed")
    (art / "active_genome.json").write_text(
        __import__("json").dumps(
            {"genome_id": "g_seed", "path": str(art / "genomes" / "seed")}
        ),
        encoding="utf-8",
    )

    exp = {
        "eval": {"train_seeds": [0, 1]},
        "paths": {
            "artifacts_dir": str(art),
            "seed_genome": str(seed_dir),
        },
        "genomic": {
            "mutate_every_episodes": 2,
            "plateau_episodes": 50,
            "max_mutations": 2,
        },
        "evolve": {
            "mutate_every_episodes": 2,
            "plateau_episodes": 50,
            "max_mutations": 2,
            "plateau_epsilon": 0.01,
        },
    }
    world = WorldConfig(height=10, width=10, T=25, food_density=0.1, vision=2)
    fit = FitnessConfig(T=25, energy_max=100, epsilon_accept=0.0, lambda_std=0.0)
    store = Store(tmp_path / "e.sqlite")
    cfg = EvolveConfig.from_exp(exp, dry_run=True, ablation="Bc")
    cfg.mutate_every_episodes = 2
    cfg.max_mutations = 2

    report = run_evolve(
        exp=exp,
        world=world,
        fit=fit,
        wcfg=WeightConfig(),
        store=store,
        artifacts_dir=art,
        max_eval_cycles=4,
        cfg=cfg,
        train_seeds=[0, 1],
    )
    store.close()
    assert report.episodes_run >= 4
    assert report.mutations_attempted >= 1
    assert (art / "last_evolve_report.json").exists()
