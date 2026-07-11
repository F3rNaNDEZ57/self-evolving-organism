"""Structured mutation memory retrieval."""

from pathlib import Path

from organism.mutation_memory import format_lessons_for_prompt, retrieve_mutation_lessons
from organism.persistence import Store


def test_retrieve_and_format_lessons(tmp_path: Path):
    store = Store(tmp_path / "m.sqlite")
    store.insert_mutation(
        "m1",
        "g0",
        "g1",
        "failed",
        "candidate crashed: Observation.ticks",
        {"rationale": "bad ticks", "critic": {"code": "contract_break"}, "parent_fitness": 1.0},
    )
    store.insert_mutation(
        "m2",
        "g0",
        "g2",
        "accepted",
        "fitness improved",
        {"rationale": "greedier", "critic": {"code": "approve"}, "parent_fitness": 1.0, "candidate_fitness": 2.0},
    )
    lessons = retrieve_mutation_lessons(store, k=5, parent_genome_id="g0")
    assert len(lessons) >= 2
    text = format_lessons_for_prompt(lessons)
    assert "tick not ticks" in text or "Observation fields" in text
    assert "failed" in text or "accepted" in text
    store.close()
