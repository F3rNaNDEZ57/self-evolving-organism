"""
Operator job runner: launch seo CLI as a subprocess, persist status + logs.

UI is not the organism brain — it only starts/monitors the same CLI paths.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from organism.config import ROOT


# CLI writes these under artifacts/; we snapshot per job when the process exits.
KIND_RESULT_ARTIFACTS: dict[str, str] = {
    "mutate": "last_mutation_result.json",
    "evolve": "last_evolve_report.json",
    "ablate": "last_ablation_report.json",
}


@dataclass
class JobRecord:
    job_id: str
    kind: str  # mutate | evolve | ablate | weights_train | docker_smoke | custom
    argv: list[str]
    status: str = "queued"  # queued | running | succeeded | failed | killed
    pid: int | None = None
    created_at: float = 0.0
    started_at: float | None = None
    ended_at: float | None = None
    returncode: int | None = None
    log_path: str = ""
    meta_path: str = ""
    result_path: str = ""  # per-job final snapshot (params + log + CLI artifact)
    error: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> JobRecord:
        return cls(
            job_id=str(d["job_id"]),
            kind=str(d.get("kind") or "custom"),
            argv=list(d.get("argv") or []),
            status=str(d.get("status") or "queued"),
            pid=d.get("pid"),
            created_at=float(d.get("created_at") or 0.0),
            started_at=d.get("started_at"),
            ended_at=d.get("ended_at"),
            returncode=d.get("returncode"),
            log_path=str(d.get("log_path") or ""),
            meta_path=str(d.get("meta_path") or ""),
            result_path=str(d.get("result_path") or ""),
            error=str(d.get("error") or ""),
            note=str(d.get("note") or ""),
        )


def jobs_dir(artifacts_dir: Path) -> Path:
    d = Path(artifacts_dir) / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def lock_path(artifacts_dir: Path) -> Path:
    return jobs_dir(artifacts_dir) / "current.lock"


def _seo_argv(extra: list[str]) -> list[str]:
    """Prefer installed seo entry; fall back to python -m organism.cli."""
    # Use same interpreter so venv packages apply
    return [sys.executable, "-m", "organism.cli", *extra]


def build_mutate_argv(*, dry_run: bool, ablation: str = "Bc", critic: bool = True) -> list[str]:
    args = ["mutate", "--ablation", ablation]
    if dry_run:
        args.append("--dry-run")
    if critic:
        args.append("--critic")
    else:
        args.append("--no-critic")
    return _seo_argv(args)


def build_evolve_argv(
    *,
    dry_run: bool,
    cycles: int = 5,
    ablation: str = "Bc",
    max_mutations: int = 5,
    every: int = 8,
    plateau: int = 20,
) -> list[str]:
    args = [
        "evolve",
        "--cycles",
        str(cycles),
        "--ablation",
        ablation,
        "--max-mutations",
        str(max_mutations),
        "--every",
        str(every),
        "--plateau",
        str(plateau),
    ]
    if dry_run:
        args.append("--dry-run")
    else:
        args.append("--live")
    return _seo_argv(args)


def build_ablate_argv(*, dry_run: bool, max_mutations: int = 3, quick: bool = False) -> list[str]:
    args = ["ablate", "--max-mutations", str(max_mutations)]
    if quick:
        args.append("--quick")
    # quick suite defaults to dry; still pass flags explicitly for clarity
    if dry_run or quick:
        args.append("--dry-run")
    else:
        args.append("--live")
    return _seo_argv(args)


def build_weights_train_argv(*, passes: int = 2) -> list[str]:
    return _seo_argv(["weights", "train", "--passes", str(passes)])


def build_docker_smoke_argv() -> list[str]:
    return _seo_argv(["docker-smoke"])


def parse_cli_params(argv: list[str]) -> dict[str, Any]:
    """
    Parse seo CLI argv into structured operator-facing parameters.

    Handles flags used by mutate / evolve / ablate / weights train / docker-smoke.
    Unknown tokens are collected under raw_tokens for transparency.
    """
    tokens = list(argv or [])
    # Drop interpreter / -m organism.cli prefix if present
    for i, t in enumerate(tokens):
        if t in ("organism.cli", "seo") or t.endswith("organism.cli"):
            tokens = tokens[i + 1 :]
            break
        if t == "-m" and i + 1 < len(tokens) and "organism.cli" in tokens[i + 1]:
            tokens = tokens[i + 2 :]
            break

    params: dict[str, Any] = {}
    if not tokens:
        return params

    command = tokens[0]
    rest = tokens[1:]
    # weights train → command "weights train"
    if command == "weights" and rest and rest[0] == "train":
        params["command"] = "weights train"
        rest = rest[1:]
    else:
        params["command"] = command

    i = 0
    bool_flags = {
        "--dry-run": ("dry_run", True),
        "--live": ("live", True),
        "--critic": ("critic", True),
        "--no-critic": ("critic", False),
        "--quick": ("quick", True),
        "--host": ("host", True),
        "--docker": ("docker", True),
    }
    value_flags = {
        "--ablation": "ablation",
        "--cycles": "cycles",
        "--max-mutations": "max_mutations",
        "--every": "every",
        "--plateau": "plateau",
        "--passes": "passes",
        "--parent-id": "parent_id",
        "--arms": "arms",
        "--genome-id": "genome_id",
        "--label": "label",
        "--weights": "weights",
        "--seeds": "seeds",
    }
    unknown: list[str] = []
    while i < len(rest):
        t = rest[i]
        if t in bool_flags:
            key, val = bool_flags[t]
            params[key] = val
            i += 1
            continue
        if t in value_flags and i + 1 < len(rest):
            key = value_flags[t]
            raw = rest[i + 1]
            # coerce ints where obvious
            if key in (
                "cycles",
                "max_mutations",
                "every",
                "plateau",
                "passes",
                "seeds",
            ):
                try:
                    params[key] = int(raw)
                except ValueError:
                    params[key] = raw
            else:
                params[key] = raw
            i += 2
            continue
        if t.startswith("-"):
            # --flag=value form
            if "=" in t:
                k, _, v = t.partition("=")
                name = value_flags.get(k) or k.lstrip("-").replace("-", "_")
                params[name] = v
            else:
                unknown.append(t)
            i += 1
            continue
        unknown.append(t)
        i += 1

    # Normalize live vs dry for display (CLI defaults when flag omitted)
    cmd = str(params.get("command") or "")
    if "dry_run" not in params and "live" in params:
        params["dry_run"] = not bool(params["live"])
    if "live" not in params and "dry_run" in params:
        params["live"] = not bool(params["dry_run"])
    if cmd in ("mutate", "evolve", "ablate") and "dry_run" not in params:
        # mutate/evolve/ablate without --dry-run means live (or suite default)
        params["dry_run"] = False
        params["live"] = True
    if cmd == "mutate" and "critic" not in params:
        params["critic"] = True  # CLI default --critic

    if unknown:
        params["extra_args"] = unknown
    return params


def job_parameters(rec: JobRecord) -> dict[str, Any]:
    """Full operator view: record fields + parsed CLI params + derived timing."""
    cli = parse_cli_params(rec.argv)
    duration_s: float | None = None
    if rec.started_at:
        end = rec.ended_at if rec.ended_at else time.time()
        duration_s = max(0.0, float(end) - float(rec.started_at))
    return {
        "job_id": rec.job_id,
        "kind": rec.kind,
        "status": rec.status,
        "pid": rec.pid,
        "returncode": rec.returncode,
        "note": rec.note,
        "error": rec.error,
        "created_at": rec.created_at,
        "started_at": rec.started_at,
        "ended_at": rec.ended_at,
        "duration_s": duration_s,
        "log_path": rec.log_path,
        "meta_path": rec.meta_path,
        "result_path": rec.result_path,
        "argv": list(rec.argv),
        "cli": cli,
    }


def read_log(artifacts_dir: Path, job_id: str, *, max_bytes: int | None = None) -> str:
    """Read job log (full file unless max_bytes is set — then last N bytes)."""
    rec = load_job(artifacts_dir, job_id)
    if not rec or not rec.log_path:
        return ""
    p = Path(rec.log_path)
    if not p.exists():
        return ""
    data = p.read_bytes()
    if max_bytes is not None and len(data) > max_bytes:
        data = data[-max_bytes:]
    return data.decode("utf-8", errors="replace")


def load_job_result(artifacts_dir: Path, job_id: str) -> dict[str, Any] | None:
    """Load per-job final snapshot if present."""
    rec = load_job(artifacts_dir, job_id)
    candidates: list[Path] = []
    if rec and rec.result_path:
        candidates.append(Path(rec.result_path))
    candidates.append(jobs_dir(artifacts_dir) / f"{job_id}.result.json")
    for p in candidates:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
    return None


def snapshot_job_result(artifacts_dir: Path, rec: JobRecord) -> Path:
    """
    Persist a durable final snapshot after a job ends:
    parameters, full log (capped), and kind-specific CLI artifact if available.
    """
    artifacts_dir = Path(artifacts_dir)
    jdir = jobs_dir(artifacts_dir)
    dest = jdir / f"{rec.job_id}.result.json"
    log_text = ""
    if rec.log_path and Path(rec.log_path).exists():
        # Cap very large logs in the snapshot JSON (full log stays on disk)
        log_text = Path(rec.log_path).read_text(encoding="utf-8", errors="replace")
        if len(log_text) > 200_000:
            log_text = log_text[-200_000:]

    artifact_name = KIND_RESULT_ARTIFACTS.get(rec.kind)
    artifact_data: Any = None
    artifact_src = ""
    if artifact_name:
        src = artifacts_dir / artifact_name
        if src.exists():
            # Only attach if written during/after this job started
            try:
                mtime = src.stat().st_mtime
                started = float(rec.started_at or rec.created_at or 0.0)
                if mtime + 1.0 >= started:  # small clock skew allowance
                    artifact_data = json.loads(src.read_text(encoding="utf-8"))
                    artifact_src = str(src)
            except Exception:
                pass

    # Weights train: best-effort parse checkpoint id from log
    summary: dict[str, Any] = {
        "decision": None,
        "headline": None,
    }
    if rec.kind == "mutate" and isinstance(artifact_data, dict):
        summary["decision"] = artifact_data.get("decision")
        summary["headline"] = (
            f"{artifact_data.get('decision')}: {str(artifact_data.get('reason') or '')[:160]}"
        )
    elif rec.kind == "evolve" and isinstance(artifact_data, dict):
        summary["headline"] = (
            f"episodes={artifact_data.get('episodes_run')} "
            f"acc={artifact_data.get('mutations_accepted')} "
            f"final={artifact_data.get('final_genome_id')}"
        )
    elif rec.kind == "ablate" and isinstance(artifact_data, dict):
        delta = artifact_data.get("delta_holdout_bcw_minus_b0")
        summary["headline"] = (
            f"delta={delta} success={artifact_data.get('success')}"
        )
    elif rec.kind == "weights_train":
        for line in log_text.splitlines():
            if line.strip().startswith("Checkpoint "):
                summary["headline"] = line.strip()
                break
        if not summary["headline"]:
            for line in log_text.splitlines():
                if "train_fitness" in line.lower() or "│ train_fitness" in line:
                    summary["headline"] = line.strip()
                    break

    if not summary["headline"]:
        # last non-empty log lines
        lines = [ln for ln in log_text.strip().splitlines() if ln.strip()]
        summary["headline"] = " | ".join(lines[-3:]) if lines else rec.status

    payload = {
        "job_id": rec.job_id,
        "kind": rec.kind,
        "status": rec.status,
        "returncode": rec.returncode,
        "note": rec.note,
        "error": rec.error,
        "created_at": rec.created_at,
        "started_at": rec.started_at,
        "ended_at": rec.ended_at,
        "duration_s": (
            max(0.0, float(rec.ended_at) - float(rec.started_at))
            if rec.started_at and rec.ended_at
            else None
        ),
        "cli": parse_cli_params(rec.argv),
        "argv": list(rec.argv),
        "log_path": rec.log_path,
        "meta_path": rec.meta_path,
        "summary": summary,
        "artifact_source": artifact_src,
        "artifact": artifact_data,
        "log": log_text,
        "snapshotted_at": time.time(),
    }
    dest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return dest


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        if sys.platform == "win32":
            # OpenProcess would be better; os.kill(pid, 0) works on Windows for existence check in recent Python
            os.kill(pid, 0)
            return True
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError, PermissionError):
        return False


def read_lock(artifacts_dir: Path) -> dict[str, Any] | None:
    lp = lock_path(artifacts_dir)
    if not lp.exists():
        return None
    try:
        return json.loads(lp.read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_lock(artifacts_dir: Path) -> None:
    lp = lock_path(artifacts_dir)
    if lp.exists():
        try:
            lp.unlink()
        except OSError:
            pass


def is_busy(artifacts_dir: Path) -> tuple[bool, str]:
    """Return (busy, job_id_or_reason). Refreshes finished jobs."""
    lock = read_lock(artifacts_dir)
    if not lock:
        return False, ""
    job_id = str(lock.get("job_id") or "")
    if job_id:
        rec = load_job(artifacts_dir, job_id)
        if rec:
            rec = refresh_job(artifacts_dir, rec)
            if rec.status in ("running", "queued"):
                return True, job_id
    # stale lock
    clear_lock(artifacts_dir)
    return False, ""


def load_job(artifacts_dir: Path, job_id: str) -> JobRecord | None:
    meta = jobs_dir(artifacts_dir) / f"{job_id}.json"
    if not meta.exists():
        return None
    try:
        return JobRecord.from_dict(json.loads(meta.read_text(encoding="utf-8")))
    except Exception:
        return None


def save_job(artifacts_dir: Path, rec: JobRecord) -> Path:
    meta = jobs_dir(artifacts_dir) / f"{rec.job_id}.json"
    rec.meta_path = str(meta)
    meta.write_text(json.dumps(rec.to_dict(), indent=2), encoding="utf-8")
    return meta


def list_jobs(artifacts_dir: Path, limit: int = 50) -> list[JobRecord]:
    root = jobs_dir(artifacts_dir)
    recs: list[JobRecord] = []
    for p in sorted(root.glob("job_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            recs.append(JobRecord.from_dict(json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            continue
        if len(recs) >= limit:
            break
    return recs


def refresh_job(artifacts_dir: Path, rec: JobRecord) -> JobRecord:
    """Update status if process exited."""
    if rec.status not in ("running", "queued"):
        return rec
    if rec.pid and _pid_alive(rec.pid):
        rec.status = "running"
        save_job(artifacts_dir, rec)
        return rec
    # process gone — try to read returncode from a sidecar if we wrote one
    rc_path = jobs_dir(artifacts_dir) / f"{rec.job_id}.rc"
    if rc_path.exists():
        try:
            rec.returncode = int(rc_path.read_text(encoding="utf-8").strip())
        except Exception:
            rec.returncode = None
    if rec.returncode is None:
        # unknown exit
        rec.returncode = -1 if rec.status == "running" else rec.returncode
    rec.status = "succeeded" if rec.returncode == 0 else "failed"
    if rec.ended_at is None:
        rec.ended_at = time.time()
    # Ensure durable final snapshot exists even if watcher missed it
    if not rec.result_path or not Path(rec.result_path).exists():
        try:
            rec.result_path = str(snapshot_job_result(artifacts_dir, rec))
        except Exception:
            pass
    save_job(artifacts_dir, rec)
    lock = read_lock(artifacts_dir)
    if lock and lock.get("job_id") == rec.job_id:
        clear_lock(artifacts_dir)
    return rec


def start_job(
    artifacts_dir: Path,
    *,
    kind: str,
    argv: list[str],
    note: str = "",
    cwd: Path | None = None,
) -> JobRecord:
    """
    Start a background CLI job. Raises RuntimeError if another job is running
    or operator control blocks mutations for mutate/evolve kinds.
    """
    artifacts_dir = Path(artifacts_dir)
    busy, jid = is_busy(artifacts_dir)
    if busy:
        raise RuntimeError(f"job already running: {jid}")

    # Honor operator control for genomic jobs
    if kind in ("mutate", "evolve", "ablate"):
        from organism.observer.control import mutations_allowed

        ok, why = mutations_allowed(artifacts_dir)
        if not ok:
            raise RuntimeError(f"blocked by operator control: {why}")

    job_id = f"job_{uuid.uuid4().hex[:10]}"
    jdir = jobs_dir(artifacts_dir)
    log_path = jdir / f"{job_id}.log"
    rc_path = jdir / f"{job_id}.rc"

    rec = JobRecord(
        job_id=job_id,
        kind=kind,
        argv=list(argv),
        status="queued",
        created_at=time.time(),
        log_path=str(log_path),
        note=note,
    )
    save_job(artifacts_dir, rec)

    # Wrapper writes return code after process exits (cross-platform)
    # We launch via Popen with stdout/stderr to log file.
    log_f = open(log_path, "w", encoding="utf-8", errors="replace")
    log_f.write(f"# job {job_id} kind={kind}\n# argv: {argv}\n# cwd: {cwd or ROOT}\n\n")
    log_f.flush()

    creationflags = 0
    if sys.platform == "win32":
        # New process group so we can terminate tree later if needed
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(cwd or ROOT),
            stdout=log_f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            env={
                **os.environ,
                "PYTHONUNBUFFERED": "1",
                # Windows default cp1252 breaks Rich + ε/δ/— in mutation reasons
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            },
        )
    except Exception as e:
        log_f.write(f"\n# failed to start: {e}\n")
        log_f.close()
        rec.status = "failed"
        rec.error = str(e)
        rec.ended_at = time.time()
        save_job(artifacts_dir, rec)
        raise

    rec.pid = proc.pid
    rec.status = "running"
    rec.started_at = time.time()
    save_job(artifacts_dir, rec)

    lock_path(artifacts_dir).write_text(
        json.dumps({"job_id": job_id, "pid": proc.pid, "started_at": rec.started_at}, indent=2),
        encoding="utf-8",
    )

    # Watcher thread: wait for process, write rc, update meta
    import threading

    def _watch() -> None:
        try:
            code = proc.wait()
            rc_path.write_text(str(code), encoding="utf-8")
            log_f.write(f"\n# exit {code}\n")
        except Exception as e:
            log_f.write(f"\n# watcher error: {e}\n")
            code = -1
            try:
                rc_path.write_text(str(code), encoding="utf-8")
            except Exception:
                pass
        finally:
            try:
                log_f.close()
            except Exception:
                pass
            r = load_job(artifacts_dir, job_id)
            if r:
                r.returncode = code
                r.status = "succeeded" if code == 0 else "failed"
                r.ended_at = time.time()
                try:
                    # Small delay so CLI can finish writing last_*.json
                    time.sleep(0.15)
                    result_p = snapshot_job_result(artifacts_dir, r)
                    r.result_path = str(result_p)
                except Exception as snap_err:
                    r.error = (r.error + f"; snapshot: {snap_err}").strip("; ")
                save_job(artifacts_dir, r)
            lock = read_lock(artifacts_dir)
            if lock and lock.get("job_id") == job_id:
                clear_lock(artifacts_dir)

    t = threading.Thread(target=_watch, name=f"seo-job-{job_id}", daemon=True)
    t.start()
    return rec


def tail_log(artifacts_dir: Path, job_id: str, max_bytes: int = 24_000) -> str:
    return read_log(artifacts_dir, job_id, max_bytes=max_bytes)


def kill_job(artifacts_dir: Path, job_id: str) -> JobRecord | None:
    """Best-effort hard kill of a running job (Windows process group aware)."""
    rec = load_job(artifacts_dir, job_id)
    if not rec or not rec.pid:
        return rec
    rec = refresh_job(artifacts_dir, rec)
    if rec.status != "running":
        return rec
    pid = rec.pid
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            os.kill(pid, signal.SIGTERM)
    except Exception as e:
        rec.error = str(e)
    rec.status = "killed"
    rec.ended_at = time.time()
    save_job(artifacts_dir, rec)
    clear_lock(artifacts_dir)
    return rec
