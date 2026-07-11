"""
Phase 6 scaffold: operator health check (environment / artifacts / docker).

Does not change science. Read-only diagnostics for research-grade ops readiness.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from organism.config import ROOT, experiment_config, nim_config, resolve_path


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    severity: str = "info"  # info | warn | error

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DoctorReport:
    ok: bool
    checks: list[Check] = field(default_factory=list)
    created_at: float = 0.0
    root: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "created_at": self.created_at,
            "root": self.root,
            "checks": [c.to_dict() for c in self.checks],
            "errors": [c.name for c in self.checks if not c.ok and c.severity == "error"],
            "warns": [c.name for c in self.checks if not c.ok and c.severity == "warn"],
        }


def run_doctor(*, require_docker: bool | None = None) -> DoctorReport:
    checks: list[Check] = []
    exp = experiment_config()
    artifacts = resolve_path(exp.get("paths", {}).get("artifacts_dir", "artifacts"))
    db = resolve_path(exp.get("paths", {}).get("db_path", "artifacts/seo.sqlite"))
    seed = resolve_path(exp.get("paths", {}).get("seed_genome", "genomes/seed"))
    sb = exp.get("sandbox", {}) or {}
    need_docker = (
        bool(sb.get("require_docker", True))
        if require_docker is None
        else bool(require_docker)
    )

    # Python / package
    checks.append(
        Check("python_package", True, f"organism importable ROOT={ROOT}", "info")
    )

    # Seed genome
    seed_ok = (seed / "policy.py").exists()
    checks.append(
        Check(
            "seed_genome",
            seed_ok,
            str(seed) if seed_ok else f"missing policy.py under {seed}",
            "error" if not seed_ok else "info",
        )
    )

    # Artifacts dirs
    for sub in ("genomes", "weights", "jobs", "mutations"):
        p = artifacts / sub
        p.mkdir(parents=True, exist_ok=True)
        checks.append(Check(f"artifacts_{sub}", True, str(p), "info"))

    # DB
    try:
        from organism.persistence import Store

        store = Store(db)
        store.close()
        checks.append(Check("sqlite", True, str(db), "info"))
    except Exception as e:
        checks.append(Check("sqlite", False, str(e), "error"))

    # NIM key (presence only)
    key = os.getenv("NVIDIA_API_KEY", "")
    try:
        cfg = nim_config()
        key = key or str(cfg.get("api_key") or "")
    except Exception:
        pass
    checks.append(
        Check(
            "nvidia_api_key",
            bool(key),
            "set" if key else "missing — live NIM mutate/evolve will fail",
            "warn" if not key else "info",
        )
    )

    # Docker
    from organism.sandbox import docker_available, image_exists, SandboxConfig

    docker_ok = docker_available()
    checks.append(
        Check(
            "docker",
            docker_ok or not need_docker,
            "available" if docker_ok else "not available",
            "error" if need_docker and not docker_ok else ("warn" if not docker_ok else "info"),
        )
    )
    if docker_ok:
        img = str(sb.get("image") or SandboxConfig().image)
        exists = image_exists(img)
        checks.append(
            Check(
                "sandbox_image",
                exists,
                img if exists else f"{img} missing — run: seo docker-build",
                "warn" if not exists else "info",
            )
        )

    # Active genome
    active = artifacts / "active_genome.json"
    if active.exists():
        try:
            data = json.loads(active.read_text(encoding="utf-8"))
            ap = Path(str(data.get("path") or ""))
            ok = ap.exists() and (ap / "policy.py").exists()
            checks.append(
                Check(
                    "active_genome",
                    ok,
                    f"{data.get('genome_id')} → {ap}" if ok else f"broken path {ap}",
                    "warn" if not ok else "info",
                )
            )
        except Exception as e:
            checks.append(Check("active_genome", False, str(e), "warn"))
    else:
        checks.append(Check("active_genome", True, "none (will use seed)", "info"))

    # Control freeze
    ctrl = artifacts / "control.json"
    if ctrl.exists():
        try:
            c = json.loads(ctrl.read_text(encoding="utf-8"))
            frozen = bool(c.get("frozen"))
            paused = bool(c.get("mutations_paused"))
            checks.append(
                Check(
                    "operator_control",
                    not frozen,
                    f"paused={paused} frozen={frozen}",
                    "warn" if frozen or paused else "info",
                )
            )
        except Exception as e:
            checks.append(Check("operator_control", False, str(e), "warn"))

    # pytest available?
    checks.append(
        Check(
            "pytest",
            shutil.which("pytest") is not None
            or (ROOT / ".venv" / "Scripts" / "pytest.exe").exists(),
            "available for regression suites",
            "info",
        )
    )

    ok = not any(c.severity == "error" and not c.ok for c in checks)
    report = DoctorReport(ok=ok, checks=checks, created_at=time.time(), root=str(ROOT))
    out = artifacts / "last_doctor_report.json"
    artifacts.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return report
