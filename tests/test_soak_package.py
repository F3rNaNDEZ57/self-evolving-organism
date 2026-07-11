"""Phase 6 soak + reproduce package."""

from pathlib import Path

from organism.genome_loader import copy_genome
from organism.reproduce import package_reproduce
from organism.evaluator import FitnessConfig
from organism.persistence import Store
from organism.soak import run_soak
from organism.weights import WeightConfig
from organism.world import WorldConfig

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "genomes" / "seed"


def test_package_reproduce(tmp_path: Path):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "last_doctor_report.json").write_text('{"ok": true}', encoding="utf-8")
    # fake config copies from ROOT exist; package uses ROOT
    res = package_reproduce(art, out_root=tmp_path / "packages", include_zip=True)
    assert Path(res.dir_path).exists()
    assert (Path(res.dir_path) / "REPRODUCE.md").exists()
    assert res.zip_path and Path(res.zip_path).exists()


def test_soak_dry(tmp_path: Path):
    art = tmp_path / "art"
    art.mkdir()
    g = art / "genomes" / "seed"
    copy_genome(SEED, g)
    (art / "active_genome.json").write_text(
        __import__("json").dumps({"genome_id": "g_seed", "path": str(g)}),
        encoding="utf-8",
    )
    exp = {
        "eval": {"train_seeds": [0, 1]},
        "paths": {"artifacts_dir": str(art), "seed_genome": str(g)},
        "evolve": {
            "mutate_every_episodes": 2,
            "max_mutations": 2,
            "plateau_episodes": 50,
        },
        "sandbox": {"mode": "host", "episode_isolation": False, "require_docker": False},
    }
    world = WorldConfig(height=10, width=10, T=20, food_density=0.1, vision=2)
    fit = FitnessConfig(T=20, energy_max=100, epsilon_accept=0.0, lambda_std=0.0)
    store = Store(tmp_path / "s.sqlite")
    rep = run_soak(
        exp=exp,
        world=world,
        fit=fit,
        wcfg=WeightConfig(),
        store=store,
        artifacts_dir=art,
        rounds=2,
        evolve_cycles=1,
        dry_run=True,
        skip_doctor=True,
    )
    store.close()
    assert rep.rounds == 2
    assert (art / "last_soak_report.json").exists()
    assert len(rep.round_reports) == 2
