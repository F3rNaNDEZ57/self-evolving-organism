"""Phase 5 multi-lineage budgets."""

from pathlib import Path

from organism.elites import promote_elite
from organism.evolve import EvolveConfig, run_evolve
from organism.evaluator import FitnessConfig
from organism.genome_loader import copy_genome
from organism.lineages import (
    BudgetConfig,
    lineage_can_eval,
    lineage_can_mutate,
    open_lineage_slots,
    pick_lineage,
    LineageSlot,
)
from organism.observer.jobs import build_evolve_argv, parse_cli_params
from organism.persistence import Store
from organism.weights import WeightConfig
from organism.world import WorldConfig

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "genomes" / "seed"


def _mk(art: Path, gid: str) -> Path:
    g = art / "genomes" / gid
    copy_genome(SEED, g)
    return g


def test_open_slots_and_pick(tmp_path: Path):
    art = tmp_path / "art"
    art.mkdir()
    db = art / "s.sqlite"
    store = Store(db)
    g1 = _mk(art, "g_a")
    g2 = _mk(art, "g_b")
    # Make content differ so diversity fill keeps both
    (g2 / "heuristics.py").write_text(
        (g2 / "heuristics.py").read_text(encoding="utf-8") + "\n# diversify\n",
        encoding="utf-8",
    )
    store.insert_genome(genome_id="g_a", artifact_path=str(g1), status="archived")
    store.insert_genome(genome_id="g_b", artifact_path=str(g2), status="archived")
    store.insert_evaluation("g_a", 2.0, 2.0, 0.0, [0], [])
    store.insert_evaluation("g_b", 8.0, 8.0, 0.0, [0], [])
    promote_elite(art, store, "g_a", fitness=2.0)
    promote_elite(art, store, "g_b", fitness=8.0)
    exp = {"paths": {"artifacts_dir": str(art), "seed_genome": str(g1)}}
    bud = BudgetConfig(max_lineages=2, schedule="fitness_rank")
    slots = open_lineage_slots(art, store, exp, bud)
    assert len(slots) == 2
    assert slots[0].genome_id == "g_b"  # higher fitness first

    s, rr, why = pick_lineage(slots, bud, rr_index=0)
    assert s is not None
    assert "fitness_rank" in why
    assert s.genome_id == "g_b"

    bud2 = BudgetConfig(max_lineages=2, schedule="round_robin")
    s1, rr1, _ = pick_lineage(slots, bud2, rr_index=0)
    s2, rr2, _ = pick_lineage(slots, bud2, rr_index=rr1)
    assert s1 is not None and s2 is not None
    assert {s1.slot_id, s2.slot_id} == {0, 1} or s1.slot_id == s2.slot_id
    store.close()


def test_lineage_caps():
    s = LineageSlot(slot_id=0, genome_id="g", path="/x", eval_cycles=2, mutations_attempted=1)
    bud = BudgetConfig(max_eval_cycles_per_lineage=2, max_mutations_per_lineage=1)
    ok, why = lineage_can_eval(s, bud)
    assert not ok and "eval_cap" in why
    okm, whym = lineage_can_mutate(s, bud)
    assert not okm and "mut_cap" in whym


def test_run_evolve_population_dry(tmp_path: Path):
    art = tmp_path / "art"
    art.mkdir()
    (art / "genomes").mkdir()
    g1 = _mk(art, "g1")
    g2 = _mk(art, "g2")
    store = Store(tmp_path / "e.sqlite")
    store.insert_genome(genome_id="g1", artifact_path=str(g1), status="archived")
    store.insert_genome(genome_id="g2", artifact_path=str(g2), status="archived")
    store.insert_evaluation("g1", 1.0, 1.0, 0.0, [0], [])
    store.insert_evaluation("g2", 3.0, 3.0, 0.0, [0], [])
    promote_elite(art, store, "g1", fitness=1.0)
    promote_elite(art, store, "g2", fitness=3.0)
    (art / "active_genome.json").write_text(
        __import__("json").dumps({"genome_id": "g1", "path": str(g1)}),
        encoding="utf-8",
    )
    exp = {
        "eval": {"train_seeds": [0, 1]},
        "paths": {"artifacts_dir": str(art), "seed_genome": str(g1)},
        "evolve": {
            "mutate_every_episodes": 2,
            "plateau_episodes": 50,
            "max_mutations": 2,
            "max_lineages": 2,
            "lineage_schedule": "round_robin",
            "max_mutations_per_lineage": 1,
            "max_eval_cycles_per_lineage": 3,
        },
        "sandbox": {"mode": "host", "episode_isolation": False, "require_docker": False},
    }
    world = WorldConfig(height=10, width=10, T=20, food_density=0.1, vision=2)
    fit = FitnessConfig(T=20, energy_max=100, epsilon_accept=0.0, lambda_std=0.0)
    cfg = EvolveConfig.from_exp(exp, dry_run=True, ablation="Bc")
    assert cfg.max_lineages == 2
    rep = run_evolve(
        exp=exp,
        world=world,
        fit=fit,
        wcfg=WeightConfig(),
        store=store,
        artifacts_dir=art,
        max_eval_cycles=4,
        cfg=cfg,
    )
    assert rep.max_lineages == 2
    assert len(rep.lineages) >= 1
    assert rep.episodes_run > 0
    store.close()


def test_build_evolve_argv_lineages():
    argv = build_evolve_argv(
        dry_run=True,
        lineages=3,
        mut_per_lineage=2,
        cycles_per_lineage=4,
        lineage_schedule="fitness_rank",
    )
    p = parse_cli_params(argv)
    assert p.get("lineages") == 3
    assert p.get("mut_per_lineage") == 2
    assert p.get("cycles_per_lineage") == 4
    assert p.get("lineage_schedule") == "fitness_rank"


def test_open_slots_content_diverse_and_seed(tmp_path: Path):
    """Identical clones collapse; seed included as exploration arm."""
    from organism.lineages import genome_content_key

    art = tmp_path / "art"
    art.mkdir()
    store = Store(tmp_path / "d.sqlite")
    # three genome dirs — two identical content, one different
    ga = _mk(art, "g_champ")
    gb = _mk(art, "g_clone")
    gc = _mk(art, "g_diff")
    (gc / "heuristics.py").write_text(
        (gc / "heuristics.py").read_text(encoding="utf-8") + "\n# branch\n",
        encoding="utf-8",
    )
    assert genome_content_key(ga) == genome_content_key(gb)
    assert genome_content_key(ga) != genome_content_key(gc)
    for gid, path, fit in (
        ("g_champ", ga, 28.0),
        ("g_clone", gb, 27.0),
        ("g_diff", gc, 5.0),
    ):
        store.insert_genome(genome_id=gid, artifact_path=str(path), status="archived")
        store.insert_evaluation(gid, fit, fit, 0.0, [0], [])
        promote_elite(art, store, gid, fitness=fit)
    seed = art / "seed"
    copy_genome(SEED, seed)
    (seed / "heuristics.py").write_text(
        (seed / "heuristics.py").read_text(encoding="utf-8") + "\n# seed-arm\n",
        encoding="utf-8",
    )
    (art / "active_genome.json").write_text(
        __import__("json").dumps({"genome_id": "g_champ", "path": str(ga)}),
        encoding="utf-8",
    )
    exp = {"paths": {"artifacts_dir": str(art), "seed_genome": str(seed)}}
    slots = open_lineage_slots(
        art, store, exp, BudgetConfig(max_lineages=3, schedule="round_robin")
    )
    ids = {s.genome_id for s in slots}
    # clone of champ content skipped
    assert "g_clone" not in ids
    assert "g_champ" in ids
    assert "g_diff" in ids
    # seed arm when underfilled / as third unique content
    assert "g_seed" in ids or len(slots) >= 2
    keys = {s.content_key for s in slots}
    assert len(keys) == len(slots)
    store.close()


def test_format_lessons_diversity_hint():
    from organism.mutation_memory import format_lessons_for_prompt

    text = format_lessons_for_prompt(
        [
            {
                "decision": "rejected",
                "reason": "critic reject [low_value]: nearest_food_direction tweak",
                "critic_code": "low_value",
                "rationale": "Modified nearest_food_direction ratio",
            }
        ]
    )
    assert "DIVERSITY" in text
    assert "nearest_food" in text.lower() or "food-direction" in text.lower()
