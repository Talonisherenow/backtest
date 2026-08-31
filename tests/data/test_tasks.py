from datetime import date, datetime, timezone
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


def test_task_manager_summarizes_tasks_by_status_and_frequency(tmp_path: Path):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    tasks = CrawlTaskManager(metadata)
    first_id = tasks.create_task(
        symbol="BTC/USDT",
        frequency=Frequency.DAILY,
        adjust=AdjustMode.NONE,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        source="ccxt:bitget",
    )
    second_id = tasks.create_task(
        symbol="ETH/USDT",
        frequency=Frequency.HOUR_4,
        adjust=AdjustMode.NONE,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        source="ccxt:bitget",
    )
    third_id = tasks.create_task(
        symbol="000858.SZ",
        frequency=Frequency.DAILY,
        adjust=AdjustMode.QFQ,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        source="akshare",
    )
    tasks.mark_success(first_id)
    tasks.mark_failed(second_id, "timeout")
    tasks.mark_running(third_id)
    with metadata.connect() as conn:
        conn.execute("UPDATE crawl_tasks SET updated_at = ? WHERE task_id = ?", ("2025-01-02T00:00:00+00:00", first_id))
        conn.execute("UPDATE crawl_tasks SET updated_at = ? WHERE task_id = ?", ("2025-01-03T00:00:00+00:00", second_id))
        conn.execute("UPDATE crawl_tasks SET updated_at = ? WHERE task_id = ?", ("2025-01-04T00:00:00+00:00", third_id))

    summary = tasks.task_summary()

    assert summary.total == 3
    assert summary.status_counts == {"failed": 1, "running": 1, "success": 1}
    assert summary.frequency_counts == {"1d": 2, "4h": 1}
    assert summary.latest_updated_at is not None
    assert summary.latest_updated_at.isoformat() == "2025-01-04T00:00:00+00:00"


def test_task_manager_lists_paginated_tasks_with_symbol_frequency_and_status_filters(tmp_path: Path):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    tasks = CrawlTaskManager(metadata)
    task_ids = []
    for index, (symbol, frequency, status) in enumerate(
        [
            ("BTC/USDT", Frequency.DAILY, "success"),
            ("BTC/USDT", Frequency.HOUR_4, "failed"),
            ("ETH/USDT", Frequency.DAILY, "running"),
            ("SOL/USDT", Frequency.HOUR_1, "success"),
        ],
        start=1,
    ):
        task_id = tasks.create_task(
            symbol=symbol,
            frequency=frequency,
            adjust=AdjustMode.NONE,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            source="ccxt:bitget",
        )
        if status == "success":
            tasks.mark_success(task_id)
        elif status == "failed":
            tasks.mark_failed(task_id, "timeout")
        else:
            tasks.mark_running(task_id)
        task_ids.append(task_id)
        with metadata.connect() as conn:
            conn.execute(
                "UPDATE crawl_tasks SET updated_at = ? WHERE task_id = ?",
                (f"2025-01-0{index}T00:00:00+00:00", task_id),
            )

    first_page = tasks.list_tasks_page(page=1, page_size=2)
    second_page = tasks.list_tasks_page(page=2, page_size=2)
    filtered = tasks.list_tasks_page(
        page=1,
        page_size=10,
        symbol="btc",
        frequencies=[Frequency.DAILY, Frequency.HOUR_4],
        statuses=["success", "failed"],
    )
    capped = tasks.list_tasks_page(page=1, page_size=500)

    assert first_page.total == 4
    assert first_page.total_pages == 2
    assert [task.symbol for task in first_page.tasks] == ["SOL/USDT", "ETH/USDT"]
    assert [task.symbol for task in second_page.tasks] == ["BTC/USDT", "BTC/USDT"]
    assert [(task.symbol, task.frequency.value, task.status) for task in filtered.tasks] == [
        ("BTC/USDT", "4h", "failed"),
        ("BTC/USDT", "1d", "success"),
    ]
    assert capped.page_size == 100


def test_task_manager_purges_tasks_older_than_retention_window(tmp_path: Path):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    tasks = CrawlTaskManager(metadata)
    old_id = tasks.create_task(
        symbol="BTC/USDT",
        frequency=Frequency.DAILY,
        adjust=AdjustMode.NONE,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 2),
        source="ccxt:bitget",
    )
    new_id = tasks.create_task(
        symbol="ETH/USDT",
        frequency=Frequency.DAILY,
        adjust=AdjustMode.NONE,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 2),
        source="ccxt:bitget",
    )
    with metadata.connect() as conn:
        conn.execute(
            "UPDATE crawl_tasks SET created_at = ? WHERE task_id = ?",
            ("2026-01-01T00:00:00+00:00", old_id),
        )
        conn.execute(
            "UPDATE crawl_tasks SET created_at = ? WHERE task_id = ?",
            ("2026-08-30T12:00:00+00:00", new_id),
        )

    result = tasks.purge_older_than(
        retain_days=3,
        now=datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc),
    )

    remaining = {task.task_id for task in tasks.list_tasks()}
    assert result.deleted == 1
    assert result.retained == 1
    assert remaining == {new_id}
    assert result.cutoff.isoformat() == "2026-08-28T12:00:00+00:00"
