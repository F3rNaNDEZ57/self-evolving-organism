"""Vault Runs/ note export from machine reports."""

import json
from pathlib import Path

from organism.runs_export import export_run_note, load_report, render_note


def test_export_evolve(tmp_path: Path):
    art = tmp_path / "artifacts"
    art.mkdir()
    report = {
        "run_id": "evo_test123",
        "ablation": "Bc",
        "dry_run": True,
        "episodes_run": 16,
        "mutations_attempted": 2,
        "mutations_accepted": 1,
        "mutations_rejected": 1,
        "mutations_failed": 0,
        "start_genome_id": "g_a",
        "final_genome_id": "g_b",
        "final_genome_path": "/x",
        "fitness_history": [1.0, 2.5, 2.0],
        "events": [
            {
                "kind": "select",
                "genome_id": "g_a",
                "reason": "fitness_rank: best",
            },
            {
                "kind": "mutate_schedule",
                "decision": "accepted",
                "reason": "ok",
                "genome_id": "g_b",
            },
        ],
        "max_lineages": 2,
        "lineage_schedule": "round_robin",
        "lineages": [
            {
                "slot_id": 0,
                "genome_id": "g_a",
                "fitness": 1.0,
                "eval_cycles": 2,
                "mutations_attempted": 1,
                "exhausted": False,
            },
            {
                "slot_id": 1,
                "genome_id": "g_b",
                "fitness": 2.5,
                "eval_cycles": 2,
                "mutations_attempted": 1,
                "exhausted": False,
            },
        ],
        "budgets": {"max_lineages": 2},
    }
    (art / "last_evolve_report.json").write_text(
        json.dumps(report), encoding="utf-8"
    )
    vault = tmp_path / "Runs"
    vault.mkdir()
    (vault / "README.md").write_text(
        "## Index\n\n| Date | Note | Baseline | Result |\n"
        "|------|------|----------|--------|\n"
        "| 2026-01-01 | [[old]] | x | y |\n",
        encoding="utf-8",
    )
    res = export_run_note(
        art,
        kind="evolve",
        vault_runs=vault,
        update_index=True,
        force=True,
    )
    assert res.path.exists()
    text = res.path.read_text(encoding="utf-8")
    assert "evo_test123" in text
    assert "Lineage slots" in text
    assert "g_b" in text
    assert res.kind == "population"
    readme = (vault / "README.md").read_text(encoding="utf-8")
    assert res.path.stem in readme


def test_export_ablate_and_mutation(tmp_path: Path):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "last_ablation_report.json").write_text(
        json.dumps(
            {
                "run_id": "abl_x",
                "delta_holdout_bcw_minus_b0": 1.5,
                "delta_success": 0.3,
                "success": True,
                "dry_run": False,
                "arms": [{"name": "B0", "holdout_fitness": 1.0}],
            }
        ),
        encoding="utf-8",
    )
    (art / "last_mutation_result.json").write_text(
        json.dumps(
            {
                "mutation_id": "m_abc",
                "decision": "rejected",
                "reason": "low fitness",
                "parent_genome_id": "g1",
                "candidate_genome_id": "g2",
                "parent_fitness": 1.0,
                "candidate_fitness": 0.9,
                "epsilon": 0.05,
            }
        ),
        encoding="utf-8",
    )
    vault = tmp_path / "Runs"
    vault.mkdir()
    r1 = export_run_note(art, kind="ablate", vault_runs=vault, update_index=False)
    assert "success" in r1.path.read_text(encoding="utf-8").lower()
    r2 = export_run_note(art, kind="mutation", vault_runs=vault, update_index=False)
    assert "m_abc" in r2.path.read_text(encoding="utf-8")
    k, data, _ = load_report(art, "auto")
    assert k in ("ablate", "mutation", "evolve", "population")
    assert data
