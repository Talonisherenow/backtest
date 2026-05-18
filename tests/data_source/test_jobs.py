from datetime import datetime, timedelta
import time
from threading import Event, Thread

import pytest

from backtest.data.jobs import JobResult
from backtest.data_source.jobs import DataSourceJobRegistry, DataSourceJobSnapshot


def test_snapshot_to_dict_serializes_datetimes():
    snapshot = DataSourceJobSnapshot(
        job_id="job-1",
        name="Demo",
        status="success",
        submitted_at=datetime(2025, 1, 1, 9, 0, 0),
        started_at=datetime(2025, 1, 1, 9, 1, 0),
        finished_at=datetime(2025, 1, 1, 9, 2, 0),
        total_items=2,
        success_count=2,
        failed_count=0,
        total_rows=18,
        error=None,
    )

    assert snapshot.to_dict() == {
        "job_id": "job-1",
        "name": "Demo",
        "status": "success",
        "submitted_at": "2025-01-01T09:00:00",
        "started_at": "2025-01-01T09:01:00",
        "finished_at": "2025-01-01T09:02:00",
        "total_items": 2,
        "success_count": 2,
        "failed_count": 0,
        "total_rows": 18,
        "error": None,
    }


def test_inline_submit_tracks_successful_job_result():
    now_values = iter(
        [
            datetime(2025, 1, 1, 9, 0, 0),
            datetime(2025, 1, 1, 9, 0, 1),
            datetime(2025, 1, 1, 9, 0, 2),
        ]
    )

    def run_job(config):
        return JobResult(
            name=config["name"],
            started_at=datetime(2025, 1, 1, 9, 0, 1),
            finished_at=datetime(2025, 1, 1, 9, 0, 2),
            items=[],
        )

    registry = DataSourceJobRegistry(run_job, now=lambda: next(now_values), run_inline=True)

    snapshot = registry.submit({"name": "Nightly Sync"})

    assert snapshot.job_id == "20250101090000-nightly-sync"
    assert snapshot.status == "success"
    assert snapshot.started_at == datetime(2025, 1, 1, 9, 0, 1)
    assert snapshot.finished_at == datetime(2025, 1, 1, 9, 0, 2)
    assert registry.get(snapshot.job_id) == snapshot


def test_inline_submit_marks_job_result_with_failed_items_as_failed():
    def run_job(config):
        result = JobResult(
            name=config["name"],
            started_at=datetime(2025, 1, 1, 9, 0, 1),
            finished_at=datetime(2025, 1, 1, 9, 0, 2),
            items=[],
        )
        result.items.append(config["failed_item"])
        return result

    failed_item = type("FailedItem", (), {"status": "failed", "rows": 0})()
    registry = DataSourceJobRegistry(
        run_job,
        now=lambda: datetime(2025, 1, 1, 9, 0, 0),
        run_inline=True,
    )

    snapshot = registry.submit({"name": "Bad Job", "failed_item": failed_item})

    assert snapshot.status == "failed"
    assert snapshot.failed_count == 1
    assert snapshot.error == "One or more job items failed"


def test_inline_submit_captures_exceptions_as_failed_snapshot():
    def run_job(config):
        raise RuntimeError("exchange offline")

    registry = DataSourceJobRegistry(
        run_job,
        now=lambda: datetime(2025, 1, 1, 9, 0, 0),
        run_inline=True,
    )

    snapshot = registry.submit({"name": "Exploding Job"})

    assert snapshot.status == "failed"
    assert snapshot.error == "exchange offline"
    assert snapshot.finished_at == datetime(2025, 1, 1, 9, 0, 0)


def test_submit_runs_job_on_background_thread_by_default():
    started = Event()
    finish = Event()
    completed = Event()
    captured = {}

    def run_job(config):
        captured["config"] = config
        started.set()
        finish.wait(timeout=2)
        result = JobResult(
            name=config["name"],
            started_at=datetime(2025, 1, 1, 9, 0, 1),
            finished_at=datetime(2025, 1, 1, 9, 0, 2),
            items=[],
        )
        completed.set()
        return result

    registry = DataSourceJobRegistry(
        run_job,
        now=lambda: datetime(2025, 1, 1, 9, 0, 0),
    )

    snapshot = registry.submit({"name": "Background Job"})

    assert snapshot.status in {"submitted", "running"}
    assert started.wait(timeout=2)
    assert registry.get(snapshot.job_id).status == "running"
    finish.set()
    assert completed.wait(timeout=2)
    assert captured["config"] == {"name": "Background Job"}
    deadline = time.monotonic() + 2
    while registry.get(snapshot.job_id).status != "success" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert registry.get(snapshot.job_id).status == "success"


def test_concurrent_same_second_submissions_reserve_distinct_job_ids():
    finish = Event()

    def run_job(config):
        finish.wait(timeout=2)
        return JobResult(
            name=config["name"],
            started_at=datetime(2025, 1, 1, 9, 0, 1),
            finished_at=datetime(2025, 1, 1, 9, 0, 2),
        )

    registry = DataSourceJobRegistry(
        run_job,
        now=lambda: datetime(2025, 1, 1, 9, 0, 0),
    )
    snapshots = []
    threads = [
        Thread(target=lambda: snapshots.append(registry.submit({"name": "Collision Job"})))
        for _ in range(2)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
    finish.set()

    assert len(snapshots) == 2
    assert len({snapshot.job_id for snapshot in snapshots}) == 2
    assert len(registry.list()) == 2


def test_list_sorts_by_submitted_time_and_unknown_get_raises():
    current = datetime(2025, 1, 1, 9, 0, 0)

    def now():
        nonlocal current
        value = current
        current = current + timedelta(seconds=1)
        return value

    registry = DataSourceJobRegistry(
        lambda config: JobResult(name=config["name"], started_at=now(), finished_at=now()),
        now=now,
        run_inline=True,
    )

    first = registry.submit({"name": "First"})
    second = registry.submit({"name": "Second"})

    assert [snapshot.job_id for snapshot in registry.list()] == [first.job_id, second.job_id]
    with pytest.raises(ValueError, match="Unknown job"):
        registry.get("missing")
