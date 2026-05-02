from datetime import date
from pathlib import Path

from backtest.core.enums import AdjustMode, Frequency
from backtest.data.metadata import MetadataStore
from backtest.data.tasks import CrawlTaskManager


def test_task_manager_lifecycle_and_failed_retry_selection(tmp_path: Path):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    tasks = CrawlTaskManager(metadata)

    task_id = tasks.create_task(
        symbol="000001.SZ",
        frequency=Frequency.DAILY,
        adjust=AdjustMode.QFQ,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        source="fixture",
    )
    tasks.mark_running(task_id)
    tasks.mark_failed(task_id, "timeout")

    failed = tasks.failed_tasks()

    assert failed[0].task_id == task_id
    assert failed[0].status == "failed"
    assert failed[0].attempts == 1
    assert failed[0].last_error == "timeout"
