"""Phase 4 observer control plane + data helpers."""

from pathlib import Path

from organism.observer.control import (
    ControlState,
    load_control,
    mutations_allowed,
    save_control,
)
from organism.observer.data import list_genomes, list_mutations, open_store
from organism.persistence import Store


def test_control_pause_freeze(tmp_path: Path):
    art = tmp_path / "artifacts"
    art.mkdir()
    ok, _ = mutations_allowed(art)
    assert ok
    save_control(art, ControlState(mutations_paused=True, note="test pause"))
    ok, why = mutations_allowed(art)
    assert not ok
    assert "paused" in why
    st = load_control(art)
    assert st.mutations_paused
    save_control(art, ControlState(frozen=True, note="freeze"))
    ok, why = mutations_allowed(art)
    assert not ok
    assert "frozen" in why
    save_control(art, ControlState())
    assert mutations_allowed(art)[0]


def test_data_lists_empty_db(tmp_path: Path):
    db = tmp_path / "t.sqlite"
    store = open_store(db)
    assert list_genomes(store) == []
    assert list_mutations(store) == []
    store.insert_genome(genome_id="g1", status="active", artifact_path=str(tmp_path))
    store.insert_mutation("m1", "g1", "g2", "rejected", "test", {"parent_fitness": 1.0})
    assert len(list_genomes(store)) == 1
    muts = list_mutations(store)
    assert muts[0]["id"] == "m1"
    assert muts[0]["meta"]["parent_fitness"] == 1.0
    store.close()
