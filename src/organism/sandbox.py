"""Docker-backed execution helpers for untrusted genome code (Phase 2)."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SandboxConfig:
    mode: str = "docker"
    image: str = "python:3.12-slim"
    network: str = "none"
    memory: str = "512m"
    cpus: str = "1"
    require_docker: bool = True


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except Exception:
        return False


def run_python_in_docker(
    code: str,
    *,
    cfg: SandboxConfig,
    work_mount: Path | None = None,
    timeout_s: int = 30,
) -> subprocess.CompletedProcess[str]:
    """
    Run a Python snippet in a locked-down container.
    Host evaluator still runs in-process; this is for untrusted candidate checks.
    """
    if cfg.mode != "docker":
        raise RuntimeError("Only docker mode is supported for untrusted code in Phase 2 scaffold")
    if not docker_available():
        raise RuntimeError("Docker is required but not available")

    cmd = [
        "docker",
        "run",
        "--rm",
        f"--network={cfg.network}",
        f"--memory={cfg.memory}",
        f"--cpus={cfg.cpus}",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,size=64m",
    ]
    if work_mount is not None:
        cmd += ["-v", f"{work_mount.resolve()}:/work:ro", "-w", "/work"]
    cmd += [cfg.image, "python", "-c", code]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)


def smoke_network_block(cfg: SandboxConfig | None = None) -> dict[str, Any]:
    cfg = cfg or SandboxConfig()
    code = (
        "import socket\n"
        "print('python_ok')\n"
        "try:\n"
        "  socket.create_connection(('1.1.1.1', 53), timeout=2)\n"
        "  print('NETWORK_LEAK')\n"
        "except Exception as e:\n"
        "  print('network_blocked', type(e).__name__)\n"
        "print('smoke_pass')\n"
    )
    proc = run_python_in_docker(code, cfg=cfg, timeout_s=120)
    out = (proc.stdout or "") + (proc.stderr or "")
    return {
        "returncode": proc.returncode,
        "output": out.strip(),
        "ok": proc.returncode == 0 and "smoke_pass" in out and "NETWORK_LEAK" not in out,
    }
