"""
Phase 6: short soak harness — repeated dry evolve + doctor gate.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from organism.doctor import run_doctor
from organism.evaluator import FitnessConfig
from organism.evolve import EvolveConfig, run_evolve
from organism.persistence import Store
from organism.weights import WeightConfig
from organism.world import WorldConfig


@dataclass
class SoakReport:
    run_id: str
    ok: bool
    doctor_ok: bool
    rounds: int
    evolve_cycles: int
    total_mutations_attempted: int
    total_mutations_accepted: int
    round_reports: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    created_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_soak(
    *,
    exp: dict[str, Any],
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    store: Store,
    artifacts_dir: Path,
    rounds: int = 3,
    evolve_cycles: int = 2,
    dry_run: bool = True,
    ablation: str = "Bc",
    skip_doctor: bool = False,
) -> SoakReport:
    """
    Run doctor (optional), then N dry evolve rounds. Fail-soft: collect errors.
    """
    artifacts_dir = Path(artifacts_dir)
    run_id = f"soak_{int(time.time())}"
    doctor_ok = True
    errors: list[str] = []
    if not skip_doctor:
        doc = run_doctor(require_docker=False)
        doctor_ok = doc.ok
        if not doc.ok:
            errors.append(
                "doctor failed: "
                + ", ".join(
                    c.name for c in doc.checks if not c.ok and c.severity == "error"
                )
            )

    rounds = max(1, int(rounds))
    evolve_cycles = max(1, int(evolve_cycles))
    cfg = EvolveConfig.from_exp(exp, dry_run=dry_run, ablation=ablation)
    cfg.max_mutations = max(cfg.max_mutations, evolve_cycles)
    cfg.select = "active"
    cfg.max_lineages = 1

    round_reports: list[dict[str, Any]] = []
    mut_att = mut_acc = 0
    for i in range(rounds):
        try:
            rep = run_evolve(
                exp=exp,
                world=world,
                fit=fit,
                wcfg=wcfg,
                store=store,
                artifacts_dir=artifacts_dir,
                max_eval_cycles=evolve_cycles,
                cfg=cfg,
            )
            mut_att += rep.mutations_attempted
            mut_acc += rep.mutations_accepted
            round_reports.append(
                {
                    "round": i + 1,
                    "run_id": rep.run_id,
                    "episodes": rep.episodes_run,
                    "mutations_attempted": rep.mutations_attempted,
                    "mutations_accepted": rep.mutations_accepted,
                    "final_genome": rep.final_genome_id,
                    "fitness_last": (
                        rep.fitness_history[-1] if rep.fitness_history else None
                    ),
                }
            )
        except Exception as e:
            errors.append(f"round {i + 1}: {type(e).__name__}: {e}")
            round_reports.append({"round": i + 1, "error": str(e)})

    ok = doctor_ok and not errors
    report = SoakReport(
        run_id=run_id,
        ok=ok,
        doctor_ok=doctor_ok,
        rounds=rounds,
        evolve_cycles=evolve_cycles,
        total_mutations_attempted=mut_att,
        total_mutations_accepted=mut_acc,
        round_reports=round_reports,
        errors=errors,
        created_at=time.time(),
    )
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "last_soak_report.json").write_text(
        json.dumps(report.to_dict(), indent=2), encoding="utf-8"
    )
    soak_dir = artifacts_dir / "soak"
    soak_dir.mkdir(parents=True, exist_ok=True)
    (soak_dir / f"{run_id}.json").write_text(
        json.dumps(report.to_dict(), indent=2), encoding="utf-8"
    )
    store.log_event("soak_end", report.to_dict())
    return report
