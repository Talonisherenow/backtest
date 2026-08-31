from datetime import date
from pathlib import Path
from threading import Event

from backtest.core.enums import AdjustMode, Frequency
from backtest.data.metadata import MetadataStore
from backtest.data.tasks import CrawlTaskManager
from backtest.data_source.api import DataSourceApi
from backtest.data_source.config import DataSourceServerConfig, DataSourceSpec
from backtest.data_source.jobs import DataSourceJobRegistry
from backtest.data_source.task_summary_cache import CrawlTaskSummaryRefresher


def _api(tmp_path: Path, *, refresh_seconds: float = 30.0) -> DataSourceApi:
    bars_root = tmp_path / "bars"
    bars_root.mkdir()
    metadata_path = tmp_path / "metadata.sqlite"
    spec = DataSourceSpec(
        source_id="a_share",
        source_label="A-share",
        asset_class="equity",
        bars_root=bars_root,
        metadata_path=metadata_path,
        adjust="qfq",
        catalog_source="akshare",
    )
    return DataSourceApi(
        DataSourceServerConfig(
            sources=[spec],
            task_summary_refresh_seconds=refresh_seconds,
        ),
        DataSourceJobRegistry(lambda config: None, run_inline=True),
    )


def test_task_summary_reads_cache_after_refresh(tmp_path: Path):
    api = _api(tmp_path)
    tasks = CrawlTaskManager(MetadataStore(api.config.source("a_share").metadata_path))
    task_id = tasks.create_task(
        "000001.SZ",
        Frequency.DAILY,
        AdjustMode.QFQ,
        date(2025, 1, 1),
        date(2025, 1, 2),
        "akshare",
    )
    tasks.mark_failed(task_id, "timeout")

    first = api.task_summary("a_share")
    assert first["from_cache"] is False
    assert first["status_counts"] == {"failed": 1}
    assert first["cached_at"]

    second = api.task_summary("a_share")
    assert second["from_cache"] is True
    assert second["status_counts"] == {"failed": 1}
    assert second["cached_at"] == first["cached_at"]

    tasks.mark_success(task_id)
    stale = api.task_summary("a_share")
    assert stale["from_cache"] is True
    assert stale["status_counts"] == {"failed": 1}

    fresh = api.task_summary("a_share", fresh=True)
    assert fresh["from_cache"] is False
    assert fresh["status_counts"] == {"success": 1}


def test_refresh_task_summaries_keeps_previous_payload_on_failure(tmp_path: Path, monkeypatch):
    api = _api(tmp_path)
    tasks = CrawlTaskManager(MetadataStore(api.config.source("a_share").metadata_path))
    task_id = tasks.create_task(
        "000001.SZ",
        Frequency.DAILY,
        AdjustMode.QFQ,
        date(2025, 1, 1),
        date(2025, 1, 2),
        "akshare",
    )
    tasks.mark_failed(task_id, "timeout")
    api.refresh_task_summaries()
    cached = api.task_summary("a_share")
    assert cached["status_counts"] == {"failed": 1}

    def boom(_source_id: str):
        raise RuntimeError("db locked")

    monkeypatch.setattr(api, "_compute_task_summary", boom)
    api.refresh_task_summaries()
    after_failure = api.task_summary("a_share")
    assert after_failure["from_cache"] is True
    assert after_failure["status_counts"] == {"failed": 1}
    assert after_failure["refresh_error"] == "db locked"


def test_summary_refresher_ticks_until_stopped(tmp_path: Path):
    api = _api(tmp_path, refresh_seconds=0.05)
    seen = Event()
    original = api.refresh_task_summaries

    def mark_and_refresh() -> None:
        seen.set()
        original()

    api.refresh_task_summaries = mark_and_refresh  # type: ignore[method-assign]
    refresher = CrawlTaskSummaryRefresher(
        refresh_all=api.refresh_task_summaries,
        poll_seconds=0.05,
    )
    refresher.start(refresh_immediately=True)
    assert seen.wait(1.0)
    refresher.stop()
