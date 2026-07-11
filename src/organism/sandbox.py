"""Docker-backed execution helpers for untrusted genome code (Phase 2)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from organism.config import ROOT
from organism.evaluator import EpisodeSummary, EvalResult, FitnessConfig
from organism.weights import WeightConfig
from organism.world import WorldConfig

SANDBOX_IMAGE_DEFAULT = "seo-sandbox:py312"


@dataclass
class SandboxConfig:
    mode: str = "docker"  # docker | host
    image: str = SANDBOX_IMAGE_DEFAULT
    network: str = "none"
    memory: str = "512m"
    cpus: str = "1"
    require_docker: bool = True
    episode_isolation: bool = True
    # If true, also isolate trusted parent evals (stricter, slower)
    parent_isolation: bool = False
    build_context: str = ""  # default: project ROOT

    @classmethod
    def from_exp(cls, exp: dict[str, Any]) -> SandboxConfig:
        sb = exp.get("sandbox", {})
        ev = exp.get("eval", {})
        return cls(
            mode=str(sb.get("mode", "docker")),
            image=str(sb.get("image", SANDBOX_IMAGE_DEFAULT)),
            network=str(sb.get("network", "none")),
            memory=str(sb.get("memory", ev.get("container_memory", "512m"))),
            cpus=str(sb.get("cpus", ev.get("container_cpus", "1"))),
            require_docker=bool(sb.get("require_docker", True)),
            episode_isolation=bool(sb.get("episode_isolation", True)),
            parent_isolation=bool(sb.get("parent_isolation", False)),
            build_context=str(sb.get("build_context", "")),
        )


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


def image_exists(image: str) -> bool:
    if not docker_available():
        return False
    r = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    return r.returncode == 0


def build_sandbox_image(
    *,
    image: str = SANDBOX_IMAGE_DEFAULT,
    context: Path | None = None,
    dockerfile: str = "Dockerfile.sandbox",
) -> dict[str, Any]:
    """Build the local sandbox image (needs network once for base + numpy)."""
    if not docker_available():
        raise RuntimeError("Docker is not available")
    ctx = Path(context) if context else ROOT
    df = ctx / dockerfile
    if not df.exists():
        raise FileNotFoundError(df)
    cmd = ["docker", "build", "-f", str(df), "-t", image, str(ctx)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "image": image,
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
    }


def ensure_sandbox_image(cfg: SandboxConfig, *, auto_build: bool = True) -> None:
    if cfg.mode != "docker":
        return
    if image_exists(cfg.image):
        return
    if not auto_build:
        raise RuntimeError(
            f"Sandbox image {cfg.image!r} missing. Run: seo docker-build"
        )
    result = build_sandbox_image(
        image=cfg.image,
        context=Path(cfg.build_context) if cfg.build_context else ROOT,
    )
    if not result["ok"]:
        raise RuntimeError(
            f"Failed to build sandbox image {cfg.image}: {result['stderr_tail']}"
        )


def run_python_in_docker(
    code: str,
    *,
    cfg: SandboxConfig,
    work_mount: Path | None = None,
    timeout_s: int = 30,
) -> subprocess.CompletedProcess[str]:
    if cfg.mode != "docker":
        raise RuntimeError("docker mode required")
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
    cmd += [cfg.image if image_exists(cfg.image) else "python:3.12-slim", "python", "-c", code]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)


def smoke_network_block(cfg: SandboxConfig | None = None) -> dict[str, Any]:
    cfg = cfg or SandboxConfig(image="python:3.12-slim")
    # Use slim image for smoke (no need for numpy image)
    smoke_cfg = SandboxConfig(
        mode="docker",
        image="python:3.12-slim",
        network=cfg.network,
        memory=cfg.memory,
        cpus=cfg.cpus,
    )
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
    proc = run_python_in_docker(code, cfg=smoke_cfg, timeout_s=120)
    out = (proc.stdout or "") + (proc.stderr or "")
    return {
        "returncode": proc.returncode,
        "output": out.strip(),
        "ok": proc.returncode == 0 and "smoke_pass" in out and "NETWORK_LEAK" not in out,
    }


def _vol(host: Path, container: str, mode: str = "ro") -> list[str]:
    return ["-v", f"{host.resolve()}:{container}:{mode}"]


def evaluate_genome_in_docker(
    genome_dir: Path,
    *,
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    seeds: list[int],
    ablation: str,
    cfg: SandboxConfig,
    train_weights: bool = False,
    weight_path: Path | None = None,
    timeout_s: int = 180,
    project_root: Path | None = None,
) -> EvalResult:
    """
    Run multi-seed evaluation inside Docker:
      --network none, memory/cpu caps, read-only root + tmpfs,
      bind-mount kernel src (ro) + genome (ro) + job dir (rw).
    """
    if not docker_available():
        raise RuntimeError("Docker not available for episode isolation")
    ensure_sandbox_image(cfg, auto_build=True)

    root = Path(project_root) if project_root else ROOT
    src_dir = root / "src"
    genome_dir = Path(genome_dir).resolve()
    if not (genome_dir / "policy.py").exists():
        raise FileNotFoundError(f"genome missing policy.py: {genome_dir}")

    job_dir = Path(tempfile.mkdtemp(prefix="seo_job_"))
    try:
        request = {
            "genome_dir": "/genome",
            "world": {
                "grid": [world.height, world.width],
                "T": world.T,
                "food_density": world.food_density,
                "energy_max": world.energy_max,
                "energy_start": world.energy_start,
                "drain_move": world.drain_move,
                "drain_rest": world.drain_rest,
                "forage_energy": world.forage_energy,
                "vision": world.vision,
            },
            "fitness": {
                "w1": fit.w1,
                "w2": fit.w2,
                "w3": fit.w3,
                "w4": fit.w4,
                "w5": fit.w5,
                "lambda_std": fit.lambda_std,
                "epsilon_accept": fit.epsilon_accept,
                "delta_success": fit.delta_success,
            },
            "weights": {
                "alpha": wcfg.alpha,
                "init_std": wcfg.init_std,
                "clip_abs": wcfg.clip_abs,
                "explore_train": wcfg.explore_train,
                "explore_eval": wcfg.explore_eval,
            },
            "seeds": list(seeds),
            "ablation": ablation,
            "train_weights": train_weights,
            "weight_path": "/weights/checkpoint.npz" if weight_path else None,
        }
        (job_dir / "request.json").write_text(json.dumps(request), encoding="utf-8")

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
            "-e",
            "PYTHONPATH=/app/src",
            "-e",
            "PYTHONUNBUFFERED=1",
            *_vol(src_dir, "/app/src", "ro"),
            *_vol(genome_dir, "/genome", "ro"),
            *_vol(job_dir, "/job", "rw"),
        ]
        if weight_path is not None:
            wp = Path(weight_path).resolve()
            # mount parent dir so path is stable
            cmd += ["-v", f"{wp.parent}:/weights:ro"]
            # rewrite request if filename differs
            request["weight_path"] = f"/weights/{wp.name}"
            (job_dir / "request.json").write_text(json.dumps(request), encoding="utf-8")

        cmd += [
            cfg.image,
            "python",
            "/app/src/organism/docker_worker.py",
        ]

        t0 = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)
        elapsed = time.time() - t0

        result_path = job_dir / "result.json"
        if not result_path.exists():
            raise RuntimeError(
                "docker eval produced no result.json: "
                f"rc={proc.returncode} stderr={(proc.stderr or '')[-1500:]}"
            )
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        if not payload.get("ok"):
            raise RuntimeError(
                f"docker eval failed: {payload.get('error')} "
                f"rc={proc.returncode} elapsed={elapsed:.1f}s"
            )

        episodes = []
        for ep in payload.get("episodes", []):
            episodes.append(
                EpisodeSummary(
                    seed=int(ep.get("seed", 0)),
                    score=float(ep.get("score", 0.0)),
                    food_collected=int(ep.get("food_collected", 0)),
                    ticks_survived=int(ep.get("ticks_survived", 0)),
                    final_energy=float(ep.get("final_energy", 0.0)),
                    invalid_actions=int(ep.get("invalid_actions", 0)),
                    wall_bumps=int(ep.get("wall_bumps", 0)),
                    death_reason=str(ep.get("death_reason", "")),
                )
            )
        return EvalResult(
            fitness=float(payload["fitness"]),
            mean_score=float(payload["mean_score"]),
            std_score=float(payload["std_score"]),
            episodes=episodes,
            seeds=list(payload.get("seeds", seeds)),
        )
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


def evaluate_genome(
    genome_dir: Path,
    *,
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    seeds: list[int],
    ablation: str,
    sandbox: SandboxConfig | None = None,
    train_weights: bool = False,
    weight_path: Path | None = None,
    force_host: bool = False,
    force_docker: bool = False,
) -> EvalResult:
    """
    Dispatch evaluation to Docker (isolated) or host.
    Default: docker when sandbox.episode_isolation and mode=docker.
    """
    from organism.evaluator import evaluate
    from organism.genome_loader import make_policy_factory

    sb = sandbox or SandboxConfig()
    use_docker = False
    if force_docker:
        use_docker = True
    elif force_host:
        use_docker = False
    elif sb.mode == "docker" and sb.episode_isolation:
        use_docker = True

    if use_docker:
        if not docker_available():
            if sb.require_docker:
                raise RuntimeError("Docker required for episode isolation but unavailable")
            use_docker = False

    if use_docker:
        return evaluate_genome_in_docker(
            genome_dir,
            world=world,
            fit=fit,
            wcfg=wcfg,
            seeds=seeds,
            ablation=ablation,
            cfg=sb,
            train_weights=train_weights,
            weight_path=weight_path,
        )

    factory = make_policy_factory(
        genome_dir,
        ablation=ablation,
        weight_cfg=wcfg,
        weight_path=weight_path,
        force_train=train_weights,
    )
    return evaluate(factory, world, fit, seeds, train_weights=train_weights)
