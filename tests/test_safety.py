"""Operator safety rail for ablation choice."""

import json
from pathlib import Path

from organism.safety import recommend_mutation_ablation, weights_preferred


def test_missing_diagnose_defaults_code_only(tmp_path: Path):
    prefer, why = weights_preferred(tmp_path)
    assert prefer is False
    assert "diagnose" in why.lower() or "default" in why.lower()
    abl, reason, down = recommend_mutation_ablation(tmp_path, "Bcw")
    assert abl == "Bc"
    assert down is True


def test_diagnose_negative_downgrades_bcw(tmp_path: Path):
    (tmp_path / "last_weights_diagnose.json").write_text(
        json.dumps(
            {
                "recommend_use_weights": False,
                "recommendation": "DO NOT prefer weights",
            }
        ),
        encoding="utf-8",
    )
    abl, reason, down = recommend_mutation_ablation(tmp_path, "Bcw")
    assert abl == "Bc" and down
    abl2, _, down2 = recommend_mutation_ablation(
        tmp_path, "Bcw", force_weights=True
    )
    assert abl2 == "Bcw" and not down2


def test_diagnose_positive_keeps_bcw(tmp_path: Path):
    (tmp_path / "last_weights_diagnose.json").write_text(
        json.dumps(
            {
                "recommend_use_weights": True,
                "recommendation": "USE weights",
            }
        ),
        encoding="utf-8",
    )
    abl, _, down = recommend_mutation_ablation(tmp_path, "Bcw")
    assert abl == "Bcw" and not down
