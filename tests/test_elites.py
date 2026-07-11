"""Phase 5 elite archive."""

from pathlib import Path

from organism.elites import (
    demote_elite,
    is_elite,
    list_elites,
    promote_elite,
    resolve_genome_dir,
)
from organism.mutation import resolve_parent_genome
from organism.observer.jobs import build_mutate_argv, parse_cli_params
from organism.persistence import Store


def _seed_genome(tmp: Path) -> Path:
    g = tmp / "genomes" / "g_test1"
    g.mkdir(parents=True)
    (g / "policy.py").write_text("# policy\n", encoding="utf-8")
    (g / "heuristics.py").write_text("# h\n", encoding="utf-8")
    (g / "memory_hooks.py").write_text("# m\n", encoding="utf-8")
    return g


def test_promote_list_demote(tmp_path: Path):
    art = tmp_path / "artifacts"
    art.mkdir()
    gdir = _seed_genome(art)
    db = art / "seo.sqlite"
    store = Store(db)
    store.insert_genome(
        genome_id="g_test1",
        status="archived",
        ablation="Bc",
        artifact_path=str(gdir),
    )
    store.insert_evaluation(
        genome_id="g_test1",
        fitness=12.5,
        mean_score=12.5,
        std_score=0.0,
        seeds=[0],
        episodes=[],
    )
    entry = promote_elite(art, store, "g_test1", note="keeper")
    assert entry["genome_id"] == "g_test1"
    assert is_elite(art, "g_test1")
    elites = list_elites(art)
    assert len(elites) == 1
    assert elites[0]["path_ok"] is True
    assert float(elites[0]["fitness"]) == 12.5

    path, gid = resolve_genome_dir(art, "g_test1", store=store)
    assert gid == "g_test1"
    assert path == gdir

    assert demote_elite(art, store, "g_test1") is True
    assert is_elite(art, "g_test1") is False
    store.close()


def test_resolve_parent_genome_with_parent_id(tmp_path: Path, monkeypatch):
    art = tmp_path / "artifacts"
    art.mkdir()
    gdir = _seed_genome(art)
    db = art / "seo.sqlite"
    store = Store(db)
    store.insert_genome(
        genome_id="g_test1",
        status="elite",
        ablation="Bc",
        artifact_path=str(gdir),
    )
    promote_elite(art, store, "g_test1")
    exp = {
        "paths": {
            "artifacts_dir": str(art),
            "seed_genome": str(tmp_path / "missing_seed"),
        }
    }
    # no active — must use parent_id
    path, gid = resolve_parent_genome(exp, parent_id="g_test1", store=store)
    assert gid == "g_test1"
    assert (path / "policy.py").exists()
    store.close()


def test_build_mutate_argv_parent():
    argv = build_mutate_argv(
        dry_run=True, ablation="Bc", critic=True, parent_id="g_elite1"
    )
    assert "--parent-id" in argv
    assert "g_elite1" in argv
    p = parse_cli_params(argv)
    assert p.get("parent_id") == "g_elite1"
