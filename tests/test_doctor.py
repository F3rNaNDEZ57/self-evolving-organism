"""Phase 6 doctor health check."""

from organism.doctor import run_doctor


def test_doctor_runs():
    report = run_doctor(require_docker=False)
    assert report.checks
    names = {c.name for c in report.checks}
    assert "seed_genome" in names
    assert "sqlite" in names
    assert report.to_dict()["ok"] in (True, False)
