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
    rec.ended_at = time.time()
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
                save_job(artifacts_dir, r)
            lock = read_lock(artifacts_dir)
            if lock and lock.get("job_id") == job_id:
                clear_lock(artifacts_dir)

    t = threading.Thread(target=_watch, name=f"seo-job-{job_id}", daemon=True)
    t.start()
    return rec


def tail_log(artifacts_dir: Path, job_id: str, max_bytes: int = 24_000) -> str:
    rec = load_job(artifacts_dir, job_id)
    if not rec or not rec.log_path:
        return ""
    p = Path(rec.log_path)
    if not p.exists():
        return ""
    data = p.read_bytes()
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    return data.decode("utf-8", errors="replace")


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
