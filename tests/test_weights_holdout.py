"""Bw holdout comparison B0 vs Bw(checkpoint)."""

from pathlib import Path

from organism.checkpoints import train_and_checkpoint
from organism.evaluator import FitnessConfig
from organism.genome_loader import copy_genome
from organism.observer.jobs import (
    build_weights_holdout_argv,
    build_weights_train_argv,
    parse_cli_params,
)
from organism.weights import WeightConfig
from organism.weights_holdout import run_weights_holdout
from organism.world import WorldConfig

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "genomes" / "seed"


def test_run_weights_holdout(tmp_path: Path):
    art = tmp_path / "art"
    art.mkdir()
    gdir = art / "genome"
    copy_genome(SEED, gdir)
    world = WorldConfig(height=10, width=10, T=25, food_density=0.1, vision=2)
    fit = FitnessConfig(T=25, energy_max=100, epsilon_accept=0.0, lambda_std=0.0)
    wcfg = WeightConfig()
    meta = train_and_checkpoint(
        genome_dir=gdir,
        world=world,
        wcfg=wcfg,
        train_seeds=[0, 1],
        artifacts_dir=art,
        genome_id="g_test",
        passes=1,
        ablation="Bw",
        label="t",
        fit_cfg=fit,
        eval_seeds=[0, 1],
    )
    report = run_weights_holdout(
        genome_dir=gdir,
        genome_id="g_test",
        world=world,
        fit=fit,
        wcfg=wcfg,
        holdout_seeds=[2, 3],
        artifacts_dir=art,
        weight_path=Path(meta.path),
        checkpoint_id=meta.checkpoint_id,
        force_host=True,
        train_passes=1,
    )
    assert (art / "last_weights_holdout.json").exists()
    assert report.b0.name == "B0"
    assert report.bw.name == "Bw"
    assert isinstance(report.delta_bw_minus_b0, float)


def test_build_holdout_argv():
    argv = build_weights_holdout_argv(weights="best", passes=2, host=True)
    p = parse_cli_params(argv)
    assert p.get("command") == "weights holdout"
    assert p.get("weights") == "best"
    assert p.get("passes") == 2
    assert p.get("on_seed") is not True


def test_build_holdout_argv_on_seed():
    argv = build_weights_holdout_argv(weights="latest", passes=0, host=True, on_seed=True)
    assert "--on-seed" in argv
    p = parse_cli_params(argv)
    assert p.get("command") == "weights holdout"
    assert p.get("on_seed") is True


def test_build_weights_train_argv_on_seed():
    argv = build_weights_train_argv(passes=3, on_seed=True)
    assert "--on-seed" in argv
    assert argv[argv.index("--passes") + 1] == "3"
    p = parse_cli_params(argv)
    assert p.get("command") == "weights train"
    assert p.get("passes") == 3
    assert p.get("on_seed") is True
    base = build_weights_train_argv(passes=2, on_seed=False)
    assert "--on-seed" not in base
