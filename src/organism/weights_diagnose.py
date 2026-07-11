"""
Weight training diagnostics: should we keep / use this checkpoint?

Compares B0 vs Bw on train + holdout seeds and emits a recommendation.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from organism.evaluator import FitnessConfig
from organism.sandbox import SandboxConfig, evaluate_genome
from organism.weights import WeightConfig
from organism.world import WorldConfig


@dataclass
class WeightsDiagnoseReport:
    run_id: str
    genome_id: str
    checkpoint_path: str
    train_seeds: list[int]
    holdout_seeds: list[int]
    b0_train: float
    bw_train: float
    b0_holdout: float
    bw_holdout: float
    delta_train: float
    delta_holdout: float
    recommend_use_weights: bool
    recommend_retrain: bool
    recommendation: str
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fit(
    genome_dir: Path,
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    seeds: list[int],
    *,
    ablation: str,
    weight_path: Path | None,
) -> float:
    r = evaluate_genome(
        genome_dir,
        world=world,
        fit=fit,
        wcfg=wcfg,
        seeds=seeds,
        ablation=ablation,
        train_weights=False,
        weight_path=weight_path,
        force_host=True,
        best_of_phenotype=False,
        sandbox=SandboxConfig(
            mode="host", episode_isolation=False, require_docker=False
        ),
    )
    return float(r.fitness)


def diagnose_weights(
    *,
    genome_dir: Path,
    genome_id: str,
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    train_seeds: list[int],
    holdout_seeds: list[int],
    weight_path: Path,
    artifacts_dir: Path,
    margin: float = 0.05,
) -> WeightsDiagnoseReport:
    """
    Recommend whether frozen weights beat B0 on holdout (and train).
    """
    genome_dir = Path(genome_dir)
    weight_path = Path(weight_path)
    artifacts_dir = Path(artifacts_dir)

    b0_tr = _fit(
        genome_dir, world, fit, wcfg, train_seeds, ablation="B0", weight_path=None
    )
    bw_tr = _fit(
        genome_dir,
        world,
        fit,
        wcfg,
        train_seeds,
        ablation="Bw",
        weight_path=weight_path,
    )
    b0_ho = _fit(
        genome_dir, world, fit, wcfg, holdout_seeds, ablation="B0", weight_path=None
    )
    bw_ho = _fit(
        genome_dir,
        world,
        fit,
        wcfg,
        holdout_seeds,
        ablation="Bw",
        weight_path=weight_path,
    )
    d_tr = bw_tr - b0_tr
    d_ho = bw_ho - b0_ho

    use_w = d_ho > float(margin)
    retrain = d_ho < -float(margin) or (d_tr > margin and d_ho <= 0)
    if use_w:
        rec = (
            f"USE weights on holdout (Bw-B0={d_ho:+.3f} > margin {margin}). "
            "Prefer Bw/Bcw with this checkpoint."
        )
    elif d_ho > 0:
        rec = (
            f"MARGINAL holdout gain (Bw-B0={d_ho:+.3f} <= margin {margin}). "
            "Prefer code_only phenotype / best-of; optional retrain."
        )
    else:
        rec = (
            f"DO NOT prefer weights (Bw-B0={d_ho:+.3f}). "
            "Keep heuristics (B0/Bc); retrain with more passes or different genome, "
            "or skip weight load at eval."
        )
        retrain = True

    report = WeightsDiagnoseReport(
        run_id=f"wd_{int(time.time())}",
        genome_id=genome_id,
        checkpoint_path=str(weight_path),
        train_seeds=list(train_seeds),
        holdout_seeds=list(holdout_seeds),
        b0_train=b0_tr,
        bw_train=bw_tr,
        b0_holdout=b0_ho,
        bw_holdout=bw_ho,
        delta_train=d_tr,
        delta_holdout=d_ho,
        recommend_use_weights=use_w,
        recommend_retrain=retrain,
        recommendation=rec,
        created_at=time.time(),
    )
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    out = artifacts_dir / "last_weights_diagnose.json"
    out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return report
