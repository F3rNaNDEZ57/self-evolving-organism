"""Docker-backed execution helpers for untrusted genome code (Phase 2)."""

from __future__ import annotations

import json
import os
import re
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

# Hardened docker run flags shared by smoke + genome eval
DOCKER_HARDENING_FLAGS = [
    "--cap-drop=ALL",
    "--security-opt",
    "no-new-privileges:true",
    "--pids-limit",
    "64",
    "--user",
    "1000:1000",
]


def chmod_readable_for_container(path: Path, *, recursive: bool = True) -> None:
    """
    Make bind-mounted host paths readable by the sandbox USER (uid 1000).

    tempfile.mkdtemp() and many CI runners create owner-only (0o700) dirs.
    The container runs as --user 1000:1000, which is often *not* the host
    uid on Linux CI → PermissionError on /job/request.json without this.
    """
    path = Path(path)
    if not path.exists():
        return
    try:
        if path.is_dir():
            os.chmod(path, 0o755)
            if recursive:
                for p in path.rglob("*"):
                    try:
                        os.chmod(p, 0o755 if p.is_dir() else 0o644)
                    except OSError:
                        pass
        else:
            os.chmod(path, 0o644)
    except OSError:
        # Best-effort on platforms that ignore POSIX modes (e.g. some Windows)
        pass



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
    pids_limit: int = 64
    episode_timeout_s: float = 5.0

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
            pids_limit=int(sb.get("pids_limit", 64)),
            episode_timeout_s=float(ev.get("episode_timeout_s", sb.get("episode_timeout_s", 5.0))),
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


def _hardening(cfg: SandboxConfig | None = None) -> list[str]:
    pids = str(cfg.pids_limit if cfg else 64)
    flags = list(DOCKER_HARDENING_FLAGS)
    # replace pids-limit value if custom
    if cfg and cfg.pids_limit != 64:
        for i, f in enumerate(flags):
            if f == "64" and i > 0 and flags[i - 1] == "--pids-limit":
                flags[i] = pids
                break
    return flags


def run_python_in_docker(
    code: str,
    *,
    cfg: SandboxConfig,
    work_mount: Path | None = None,
    timeout_s: int = 30,
    extra_mounts: list[str] | None = None,
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
        "/tmp:rw,size=64m,mode=1777",
        *_hardening(cfg),
    ]
    if work_mount is not None:
        cmd += ["-v", f"{work_mount.resolve()}:/work:ro", "-w", "/work"]
    if extra_mounts:
        cmd += extra_mounts
    cmd += [cfg.image if image_exists(cfg.image) else "python:3.12-slim", "python", "-c", code]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)


def smoke_network_block(cfg: SandboxConfig | None = None) -> dict[str, Any]:
    cfg = cfg or SandboxConfig(image="python:3.12-slim")
    # Use slim image for smoke (no need for numpy image); still apply hardening
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


def _parse_worker_stdout(stdout: str) -> dict[str, Any] | None:
    """Extract SEO_RESULT JSON line from worker stdout."""
    if not stdout:
        return None
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("SEO_RESULT:"):
            try:
                return json.loads(line[len("SEO_RESULT:") :].strip())
            except json.JSONDecodeError:
                continue
    # fallback: last JSON object in stream
    matches = list(re.finditer(r"\{[\s\S]*\}", stdout))
    for m in reversed(matches):
        try:
            data = json.loads(m.group(0))
            if "ok" in data or "fitness" in data:
                return data
        except json.JSONDecodeError:
            continue
    return None


def outer_eval_timeout_s(n_seeds: int, episode_timeout_s: float, margin: float = 1.5) -> int:
    """Whole-container budget derived from per-episode timeout × seeds × margin."""
    base = float(n_seeds) * float(episode_timeout_s) * float(margin) + 15.0
    return max(30, int(base))


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
    timeout_s: int | None = None,
    project_root: Path | None = None,
    episode_timeout_s: float | None = None,
) -> EvalResult:
    """
    Run multi-seed evaluation inside Docker with hardened flags:
      --network none, memory/cpu, --cap-drop=ALL, no-new-privileges,
      --pids-limit, non-root USER, read-only root + size-capped tmpfs.
    Request is bind-mounted RO; result is returned via stdout (no host rw job mount).
    """
    if not docker_available():
        raise RuntimeError("Docker not available for episode isolation")
    ensure_sandbox_image(cfg, auto_build=True)

    root = Path(project_root) if project_root else ROOT
    src_dir = root / "src"
    genome_dir = Path(genome_dir).resolve()
    if not (genome_dir / "policy.py").exists():
        raise FileNotFoundError(f"genome missing policy.py: {genome_dir}")

    ep_timeout = float(
        episode_timeout_s if episode_timeout_s is not None else cfg.episode_timeout_s
    )
    if timeout_s is None:
        timeout_s = outer_eval_timeout_s(len(seeds), ep_timeout)

    # Request only on host temp dir, mounted read-only into container
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
            "episode_timeout_s": ep_timeout,
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
            "/tmp:rw,size=64m,mode=1777",
            *_hardening(cfg),
            "-e",
            "PYTHONPATH=/app/src",
            "-e",
            "PYTHONUNBUFFERED=1",
            *_vol(src_dir, "/app/src", "ro"),
            *_vol(genome_dir, "/genome", "ro"),
            *_vol(job_dir, "/job", "ro"),  # request only — no host disk fill path
        ]
        if weight_path is not None:
            wp = Path(weight_path).resolve()
            cmd += ["-v", f"{wp.parent}:/weights:ro"]
            request["weight_path"] = f"/weights/{wp.name}"
            (job_dir / "request.json").write_text(json.dumps(request), encoding="utf-8")
            chmod_readable_for_container(wp.parent, recursive=False)
            chmod_readable_for_container(wp, recursive=False)

        # Container USER 1000 must read bind mounts (critical on Linux CI)
        chmod_readable_for_container(job_dir)
        chmod_readable_for_container(genome_dir)
        chmod_readable_for_container(src_dir)

        cmd += [
            cfg.image,
            "python",
            "/app/src/organism/docker_worker.py",
        ]

        t0 = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)
        elapsed = time.time() - t0

        payload = _parse_worker_stdout(proc.stdout or "")
        if payload is None:
            raise RuntimeError(
                "docker eval produced no SEO_RESULT: "
                f"rc={proc.returncode} stderr={(proc.stderr or '')[-1500:]} "
                f"stdout={(proc.stdout or '')[-800:]}"
            )
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


def _eval_one_phenotype(
    genome_dir: Path,
    *,
    world: WorldConfig,
    fit: FitnessConfig,
    wcfg: WeightConfig,
    seeds: list[int],
    ablation: str,
    train_weights: bool,
    weight_path: Path | None,
    use_docker: bool,
    sb: SandboxConfig,
    ep_timeout: float,
) -> EvalResult:
    from organism.evaluator import evaluate
    from organism.genome_loader import make_policy_factory

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
            episode_timeout_s=ep_timeout,
        )
    factory = make_policy_factory(
        genome_dir,
        ablation=ablation,
        weight_cfg=wcfg,
        weight_path=weight_path,
        force_train=train_weights,
    )
    return evaluate(
        factory,
        world,
        fit,
        seeds,
        train_weights=train_weights,
        episode_timeout_s=ep_timeout,
    )


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
    episode_timeout_s: float | None = None,
    best_of_phenotype: bool | None = None,
) -> EvalResult:
    """
    Dispatch evaluation to Docker (isolated) or host.
    Default: docker when sandbox.episode_isolation and mode=docker.

    For Bw/Bcw with a frozen weight checkpoint (train_weights=False), by default
    run dual phenotype eval (code-only vs with-weights) and return the better
    fitness so a weak scorer cannot tank a strong policy (D5 dual timescale).
    Set best_of_phenotype=False to force single-path eval.
    """
    sb = sandbox or SandboxConfig()
    ep_timeout = float(
        episode_timeout_s if episode_timeout_s is not None else sb.episode_timeout_s
    )
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

    # Dual-timescale best-of: only when weights are a frozen checkpoint, not mid-train
    do_best = best_of_phenotype
    if do_best is None:
        do_best = (
            ablation in ("Bw", "Bcw")
            and weight_path is not None
            and not train_weights
            and Path(weight_path).exists()
        )

    if do_best:
        code_ablation = "B0" if ablation == "Bw" else "Bc"
        code_res = _eval_one_phenotype(
            genome_dir,
            world=world,
            fit=fit,
            wcfg=wcfg,
            seeds=seeds,
            ablation=code_ablation,
            train_weights=False,
            weight_path=None,
            use_docker=use_docker,
            sb=sb,
            ep_timeout=ep_timeout,
        )
        w_res = _eval_one_phenotype(
            genome_dir,
            world=world,
            fit=fit,
            wcfg=wcfg,
            seeds=seeds,
            ablation=ablation,
            train_weights=False,
            weight_path=weight_path,
            use_docker=use_docker,
            sb=sb,
            ep_timeout=ep_timeout,
        )
        if code_res.fitness >= w_res.fitness:
            out = code_res
            ph = "code_only"
        else:
            out = w_res
            ph = "with_weights"
        out.phenotype = ph
        out.fitness_code_only = float(code_res.fitness)
        out.fitness_with_weights = float(w_res.fitness)
        return out

    return _eval_one_phenotype(
        genome_dir,
        world=world,
        fit=fit,
        wcfg=wcfg,
        seeds=seeds,
        ablation=ablation,
        train_weights=train_weights,
        weight_path=weight_path,
        use_docker=use_docker,
        sb=sb,
        ep_timeout=ep_timeout,
    )
