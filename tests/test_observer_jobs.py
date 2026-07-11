"""Phase 4.1 job runner unit tests."""

from pathlib import Path

from organism.observer.jobs import (
    build_mutate_argv,
    is_busy,
    list_jobs,
    load_job,
    start_job,
    tail_log,
)


def test_build_mutate_argv_dry():
    argv = build_mutate_argv(dry_run=True, ablation="Bc", critic=True)
    assert "mutate" in argv
    assert "--dry-run" in argv
    assert "--critic" in argv


def test_start_and_finish_job(tmp_path: Path):
    art = tmp_path / "artifacts"
    art.mkdir()
    # trivial job: python -c print
    import sys

    argv = [sys.executable, "-c", "print('hello-job')"]
    rec = start_job(art, kind="custom", argv=argv, note="unit")
    assert rec.job_id.startswith("job_")
    assert rec.status in ("running", "succeeded", "failed")
    # wait for completion
    import time

    for _ in range(50):
        r = load_job(art, rec.job_id)
        assert r is not None
        from organism.observer.jobs import refresh_job

        r = refresh_job(art, r)
        if r.status in ("succeeded", "failed", "killed"):
            break
        time.sleep(0.1)
    r = load_job(art, rec.job_id)
    assert r is not None
    assert r.status == "succeeded"
    assert r.returncode == 0
    log = tail_log(art, rec.job_id)
    assert "hello-job" in log
    assert is_busy(art)[0] is False
    assert any(j.job_id == rec.job_id for j in list_jobs(art))


def test_busy_lock_rejects_second(tmp_path: Path):
    import sys
    import time

    art = tmp_path / "artifacts"
    art.mkdir()
    argv = [sys.executable, "-c", "import time; time.sleep(2)"]
    r1 = start_job(art, kind="custom", argv=argv)
    assert r1.status == "running"
    try:
        start_job(art, kind="custom", argv=[sys.executable, "-c", "print(1)"])
        assert False, "should have raised"
    except RuntimeError as e:
        assert "already running" in str(e)
    # wait out
    time.sleep(2.5)
    from organism.observer.jobs import refresh_job

    refresh_job(art, load_job(art, r1.job_id))  # type: ignore
    assert is_busy(art)[0] is False
