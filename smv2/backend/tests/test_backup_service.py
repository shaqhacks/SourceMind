from __future__ import annotations

from app.jobs.worker import run_due_jobs_once
from app.services import jobs_service
from app.services.backup_service import run_backup, should_run_backup


def test_run_backup_creates_file_and_prunes_to_retention(client, monkeypatch):
    monkeypatch.setenv("SMV2_BACKUP_RETENTION", "2")

    # Pruning runs after every call, so with retention=2 the earlier of these
    # 4 paths are expected to be gone by the time the loop finishes — only
    # the final on-disk state (exactly `retention` files, newest survives)
    # is a meaningful assertion here.
    last_path = None
    for _ in range(4):
        last_path = run_backup()

    assert last_path.exists()
    remaining = list(last_path.parent.glob("smv2-*.db"))
    assert len(remaining) == 2
    assert last_path in remaining


def test_should_run_backup_false_when_disabled(client, monkeypatch):
    monkeypatch.setenv("SMV2_BACKUPS_ENABLED", "0")
    assert should_run_backup() is False


def test_should_run_backup_true_when_none_exist_and_enabled(client, monkeypatch):
    monkeypatch.setenv("SMV2_BACKUPS_ENABLED", "1")
    assert should_run_backup() is True


def test_backup_job_type_runs_via_worker(client):
    job = jobs_service.create_job("backup", None)
    assert run_due_jobs_once() is True

    refreshed = jobs_service.get_job(job.id)
    assert refreshed.status == "succeeded"
    assert "path" in refreshed.result
