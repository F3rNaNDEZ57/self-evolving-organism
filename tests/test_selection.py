"""Phase 5 auto parent selection."""

from pathlib import Path

from organism.elites import promote_elite
from organism.observer.jobs import build_evolve_argv, build_mutate_argv, parse_cli_params
from organism.persistence import Store
from organism.selection import gather_candidates, select_parent


def _mk_genome(root: Path, gid: str) -> Path:
    g = root / "genomes" / gid
    g.mkdir(parents=True, exist_ok=True)
    (g / "policy.py").write_text("class Policy: pass\n", encoding="utf-8")
    (g / "heuristics.py").write_text("#\n", encoding="utf-8")
    (g / "memory_hooks.py").write_text("#\n", encoding="utf-8")
    return g


def test_fitness_rank_and_tournament(tmp_path: Path):
    art = tmp_path / "artifacts"
    art.mkdir()
    db = art / "seo.sqlite"
    store = Store(db)
    g1 = _mk_genome(art, "g_low")
    g2 = _mk_genome(art, "g_high")
    store.insert_genome(genome_id="g_low", status="archived", artifact_path=str(g1))
    store.insert_genome(genome_id="g_high", status="archived", artifact_path=str(g2))
    store.insert_evaluation("g_low", 1.0, 1.0, 0.0, [0], [])
    store.insert_evaluation("g_high", 9.0, 9.0, 0.0, [0], [])
    promote_elite(art, store, "g_low", fitness=1.0)
    promote_elite(art, store, "g_high", fitness=9.0)

    import json

    exp = {"paths": {"artifacts_dir": str(art), "seed_genome": str(g1)}}
    (art / "active_genome.json").write_text(
        json.dumps({"genome_id": "g_low", "path": str(g1)}),
        encoding="utf-8",
    )

    cands = gather_candidates(art, store, exp)
    assert len(cands) >= 2

    rank = select_parent(art, store, exp, policy="fitness_rank")
    assert rank.genome_id == "g_high"
    assert rank.policy == "fitness_rank"

    # tournament with k=pool always can still pick high often; force k=2 seed many
    wins = set()
    for s in range(20):
        t = select_parent(art, store, exp, policy="tournament", tournament_k=2, seed=s)
        wins.add(t.genome_id)
        assert t.policy == "tournament"
        assert t.tournament_k == 2
    assert wins  # at least one winner
    store.close()


def test_build_argv_select():
    m = build_mutate_argv(dry_run=True, select="tournament", tournament_k=4)
    p = parse_cli_params(m)
    assert p.get("select") == "tournament"
    assert p.get("tournament_k") == 4

    e = build_evolve_argv(dry_run=True, select="fitness_rank", tournament_k=3)
    pe = parse_cli_params(e)
    assert pe.get("select") == "fitness_rank"
    assert "--select" in e
