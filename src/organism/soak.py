"""
Phase 6: soak harness — doctor gate + repeated evolve rounds.

Default is dry evolve (harness health). Use dry_run=False for live NIM soaks.
Safety rail applies: Bcw → Bc when weights diagnose is negative.
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
from organism.safety import recommend_mutation_ablation
from organism.weights import WeightConfig
from organism.world import WorldConfig


@dataclass
class SoakReport:
    run_id: str
    ok: bool
    doctor_ok: bool
    rounds: int
    evolve_cycles: int
    dry_run: bool
    ablation_requested: str
    ablation_effective: str
    safety_reason: str
    total_mutations_attempted: int
    total_mutations_accepted: int
    fitness_first: float | None = None
    fitness_last: float | None = None
    fitness_best: float | None = None
    max_mutations_per_round: int = 0
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
    max_mutations_per_round: int = 0,
    force_bcw: bool = False,
    skip_doctor: bool = False,
) -> SoakReport:
    """
    Run doctor (optional), then N evolve rounds (dry by default).

    Fail-soft: collect per-round errors; ok=False if doctor failed or any error.
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

    req_abl = (ablation or "Bc").strip()
    eff_abl, safety_why, _down = recommend_mutation_ablation(
        artifacts_dir, req_abl, force_weights=force_bcw
    )

    rounds = max(1, int(rounds))
    evolve_cycles = max(1, int(evolve_cycles))
    mut_cap = int(max_mutations_per_round)
    if mut_cap <= 0:
        mut_cap = max(1, evolve_cycles)

    cfg = EvolveConfig.from_exp(exp, dry_run=dry_run, ablation=eff_abl)
    cfg.max_mutations = mut_cap
    cfg.select = "active"
    cfg.max_lineages = 1

    round_reports: list[dict[str, Any]] = []
    mut_att = mut_acc = 0
    fitness_vals: list[float] = []

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
            f_last = rep.fitness_history[-1] if rep.fitness_history else None
            f_best = max(rep.fitness_history) if rep.fitness_history else None
            if f_last is not None:
                fitness_vals.append(float(f_last))
            round_reports.append(
                {
                    "round": i + 1,
                    "run_id": rep.run_id,
                    "episodes": rep.episodes_run,
                    "mutations_attempted": rep.mutations_attempted,
                    "mutations_accepted": rep.mutations_accepted,
                    "mutations_rejected": rep.mutations_rejected,
                    "final_genome": rep.final_genome_id,
                    "fitness_last": f_last,
                    "fitness_best": f_best,
                    "ablation": eff_abl,
                    "dry_run": dry_run,
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
        dry_run=dry_run,
        ablation_requested=req_abl,
        ablation_effective=eff_abl,
        safety_reason=safety_why,
        total_mutations_attempted=mut_att,
        total_mutations_accepted=mut_acc,
        fitness_first=fitness_vals[0] if fitness_vals else None,
        fitness_last=fitness_vals[-1] if fitness_vals else None,
        fitness_best=max(fitness_vals) if fitness_vals else None,
        max_mutations_per_round=mut_cap,
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
