"""Reproducibility package: write manifest.json per run."""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _git_sha(root: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if r.returncode == 0:
            return (r.stdout or "").strip()
    except Exception:
        pass
    return "unknown"


def _pkg_version(name: str) -> str:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return "unknown"


def build_manifest(
    *,
    run_id: str,
    run_kind: str,
    root: Path,
    exp: dict[str, Any] | None = None,
    world: dict[str, Any] | None = None,
    fitness: dict[str, Any] | None = None,
    weights: dict[str, Any] | None = None,
    nim_pins: dict[str, str] | None = None,
    rng_roots: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    packages = {
        "numpy": _pkg_version("numpy"),
        "openai": _pkg_version("openai"),
        "typer": _pkg_version("typer"),
        "pyyaml": _pkg_version("pyyaml"),
    }
    manifest: dict[str, Any] = {
        "run_id": run_id,
        "run_kind": run_kind,
        "created_at": time.time(),
        "git_sha": _git_sha(root),
        "python": {
            "version": sys.version,
            "executable": sys.executable,
            "platform": platform.platform(),
        },
        "packages": packages,
        "nim_pins": nim_pins or {},
        "world": world or {},
        "fitness": fitness or {},
        "weights": weights or {},
        "rng_roots": rng_roots or {},
        "experiment": {
            "eval": (exp or {}).get("eval"),
            "sandbox": (exp or {}).get("sandbox"),
            "genomic": (exp or {}).get("genomic"),
            "critic": (exp or {}).get("critic"),
            "ablation_suite": (exp or {}).get("ablation_suite"),
        },
    }
    if extra:
        manifest["extra"] = extra
    return manifest


def write_manifest(path: Path, manifest: dict[str, Any]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path
