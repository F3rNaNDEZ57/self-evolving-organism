"""
Bw holdout comparison: B0 vs Bw(with checkpoint) on holdout seeds.

Operator measurement helper for the dual-timescale weight gap.
Does not mutate genomes.
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
class HoldoutArm:
    name: str
    fitness: float
    mean_score: float
    std_score: float
    weight_path: str = ""
    train_weights: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WeightsHoldoutReport:
    run_id: str
    genome_id: str
    genome_path: str
    checkpoint_id: str
    checkpoint_path: str
    holdout_seeds: list[int]
    isolation: str
    b0: HoldoutArm
    bw: HoldoutArm
    delta_bw_minus_b0: float
    bw_beats_b0: bool
    train_passes: int
    created_at: float
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["b0"] = self.b0.to_dict()
        d["bw"] = self.bw.to_dict()
        return d


def run_weights_holdout(
    *,
    genome_dir: Path,
    genome_id: str,
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    holdout_seeds: list[int],
    artifacts_dir: Path,
    weight_path: Path,
    checkpoint_id: str = "",
    sandbox: SandboxConfig | None = None,
    force_host: bool = True,
    train_passes: int = 0,
) -> WeightsHoldoutReport:
    """
    Evaluate B0 (heuristics only) and Bw (frozen checkpoint) on holdout seeds.
    """
    artifacts_dir = Path(artifacts_dir)
    genome_dir = Path(genome_dir)
    weight_path = Path(weight_path)
    sb = sandbox or SandboxConfig(mode="host", episode_isolation=False, require_docker=False)
    isolation = "host" if force_host or not sb.episode_isolation else "docker"

    # Force single-path eval so we report raw B0 and raw Bw (not best-of collapse)
    b0_res = evaluate_genome(
        genome_dir,
        world=world,
        fit=fit,
        wcfg=wcfg,
        seeds=holdout_seeds,
        ablation="B0",
        sandbox=sb,
        train_weights=False,
        weight_path=None,
        force_host=force_host,
        best_of_phenotype=False,
    )
    bw_res = evaluate_genome(
        genome_dir,
        world=world,
        fit=fit,
        wcfg=wcfg,
        seeds=holdout_seeds,
        ablation="Bw",
        sandbox=sb,
        train_weights=False,
        weight_path=weight_path,
        force_host=force_host,
        best_of_phenotype=False,
    )
    # Phenotype best the organism would actually keep
    best_fit = max(float(b0_res.fitness), float(bw_res.fitness))
    best_ph = "code_only" if b0_res.fitness >= bw_res.fitness else "with_weights"

    delta = float(bw_res.fitness) - float(b0_res.fitness)
    run_id = f"wh_{int(time.time())}"
    report = WeightsHoldoutReport(
        run_id=run_id,
        genome_id=genome_id,
        genome_path=str(genome_dir),
        checkpoint_id=checkpoint_id or weight_path.stem,
        checkpoint_path=str(weight_path),
        holdout_seeds=list(holdout_seeds),
        isolation=isolation,
        b0=HoldoutArm(
            name="B0",
            fitness=float(b0_res.fitness),
            mean_score=float(b0_res.mean_score),
            std_score=float(b0_res.std_score),
        ),
        bw=HoldoutArm(
            name="Bw",
            fitness=float(bw_res.fitness),
            mean_score=float(bw_res.mean_score),
            std_score=float(bw_res.std_score),
            weight_path=str(weight_path),
            train_weights=False,
        ),
        delta_bw_minus_b0=delta,
        bw_beats_b0=delta > 0,
        train_passes=int(train_passes),
        created_at=time.time(),
        notes=(
            "Holdout comparison: B0 heuristics-only vs Bw with frozen checkpoint "
            f"(train=False). Phenotype best={best_ph} fitness={best_fit:.4f}. "
            "Positive delta means weights alone beat B0 on holdout."
        ),
    )

    out = artifacts_dir / "last_weights_holdout.json"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    wh_dir = artifacts_dir / "weights_holdout"
    wh_dir.mkdir(parents=True, exist_ok=True)
    (wh_dir / f"{run_id}.json").write_text(
        json.dumps(report.to_dict(), indent=2), encoding="utf-8"
    )
    return report
