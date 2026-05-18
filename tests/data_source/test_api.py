from datetime import date, datetime
from pathlib import Path

import pandas as pd

from backtest.core.contracts import CatalogRecord
from backtest.core.enums import AdjustMode, Frequency
from backtest.data.catalog import DataCatalog
from backtest.data.metadata import MetadataStore
from backtest.data.store import ParquetBarStore
from backtest.data.tasks import CrawlTaskManager
from backtest.data_source.api import DataSourceApi
from backtest.data_source.config import DataSourceServerConfig, DataSourceSpec
from backtest.data_source.jobs import DataSourceJobRegistry


def _write_bars(root: Path) -> None:
    ParquetBarStore(root).write_bars(
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
                "symbol": ["000001.SZ", "000001.SZ", "000001.SZ"],
                "open": [10.0, 11.0, 12.0],
                "high": [11.0, 12.0, 13.0],
                "low": [9.0, 10.0, 11.0],
                "close": [10.5, 11.5, 12.5],
                "volume": [1000, 1100, 1200],
                "amount": [10000, 11000, 12000],
                "frequency": ["1d", "1d", "1d"],
                "adjust": ["qfq", "qfq", "qfq"],
            }
        )
    )


def _api(tmp_path: Path) -> DataSourceApi:
    bars_root = tmp_path / "bars"
    _write_bars(bars_root)
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
    registry = DataSourceJobRegistry(lambda config: None, run_inline=True)
    return DataSourceApi(
        DataSourceServerConfig(sources=[spec], default_window_size=2),
        registry,
    )


def test_health_and_data_sources(tmp_path: Path):
    api = _api(tmp_path)

    assert api.health() == {"status": "ok", "service": "backtest-data-source"}
    assert api.data_sources() == {
        "sources": [
            {
                "source_id": "a_share",
                "source_label": "A-share",
                "asset_class": "equity",
                "bars": True,
                "crawl_jobs": True,
            }
        ]
    }


def test_kline_manifest_and_bars_delegate_to_cache_service(tmp_path: Path):
    api = _api(tmp_path)

    manifest = api.kline_manifest()
    bars = api.kline_bars(
        source_id="a_share",
        symbol="000001.SZ",
        frequency="1d",
        adjust="qfq",
        limit=2,
        anchor="latest",
    )

    assert manifest["default_window_size"] == 2
    assert manifest["sources"][0]["source_id"] == "a_share"
    assert bars["loaded_rows"] == 2
    assert [bar["date"] for bar in bars["bars"]] == ["2025-01-02", "2025-01-03"]


def test_tasks_inventory_and_retry_failed_serialize_real_store_records(tmp_path: Path):
    api = _api(tmp_path)
    spec = api.config.source("a_share")
    metadata = MetadataStore(spec.metadata_path)
    tasks = CrawlTaskManager(metadata)
    task_id = tasks.create_task(
        "000001.SZ",
        Frequency.DAILY,
        AdjustMode.QFQ,
        date(2025, 1, 1),
        date(2025, 1, 3),
        "akshare",
    )
    tasks.mark_failed(task_id, "timeout")
    DataCatalog(metadata).upsert(
        CatalogRecord(
            symbol="000001.SZ",
            frequency=Frequency.DAILY,
            adjust=AdjustMode.QFQ,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 3),
            rows=3,
            source="akshare",
            cache_path=spec.bars_root / "frequency=1d",
            updated_at=datetime(2025, 1, 4, 12, 0, 0),
            quality_status="ok",
        )
    )

    task_payload = api.tasks("a_share")
    paged_task_payload = api.tasks(
        "a_share",
        page=1,
        page_size=1,
        symbol="000001",
        frequencies=["1d"],
        statuses=["failed"],
    )
    task_summary = api.task_summary("a_share")
    inventory_payload = api.inventory("a_share")
    retry_payload = api.retry_failed("a_share")

    assert task_payload["tasks"][0]["frequency"] == "1d"
    assert task_payload["tasks"][0]["adjust"] == "qfq"
    assert task_payload["tasks"][0]["status"] == "failed"
    assert paged_task_payload["source_id"] == "a_share"
    assert paged_task_payload["page"] == 1
    assert paged_task_payload["page_size"] == 1
    assert paged_task_payload["total"] == 1
    assert paged_task_payload["total_pages"] == 1
    assert paged_task_payload["filters"] == {
        "symbol": "000001",
        "frequencies": ["1d"],
        "statuses": ["failed"],
    }
    assert task_summary["source_id"] == "a_share"
    assert task_summary["total"] == 1
    assert task_summary["status_counts"] == {"failed": 1}
    assert task_summary["frequency_counts"] == {"1d": 1}
    assert task_summary["latest_updated_at"] is not None
    assert inventory_payload["records"][0]["cache_path"] == str(spec.bars_root / "frequency=1d")
    assert inventory_payload["records"][0]["quality_status"] == "ok"
    assert retry_payload == {"queued": 1, "task_ids": [task_id]}
    assert api.tasks("a_share")["tasks"][0]["status"] == "retrying"


def test_submit_job_normalizes_path_fields_and_exposes_job_snapshots(tmp_path: Path):
    captured = {}

    def run_job(config):
        captured["config"] = config
        return type(
            "Result",
            (),
            {
                "name": config.name,
                "started_at": datetime(2025, 1, 1, 10, 0, 0),
                "finished_at": datetime(2025, 1, 1, 10, 1, 0),
                "total_items": 0,
                "success_count": 0,
                "failed_count": 0,
                "total_rows": 0,
            },
        )()

    api = _api(tmp_path)
    api.job_registry = DataSourceJobRegistry(
        run_job,
        now=lambda: datetime(2025, 1, 1, 9, 0, 0),
        run_inline=True,
    )

    snapshot = api.submit_job(
        {
            "name": "api job",
            "source": "ccxt",
            "exchange": "bitget",
            "symbols": ["BTC/USDT"],
            "frequencies": ["1d"],
            "adjust": "none",
            "start_date": "2025-01-01",
            "end_date": "2025-01-02",
            "bars_root": str(tmp_path / "bars"),
            "metadata": str(tmp_path / "metadata.sqlite"),
            "output_dir": str(tmp_path / "jobs"),
        }
    )

    assert captured["config"].bars_root == tmp_path / "bars"
    assert captured["config"].metadata == tmp_path / "metadata.sqlite"
    assert captured["config"].output_dir == tmp_path / "jobs"
    assert snapshot["status"] == "success"
    assert api.jobs()["jobs"][0]["job_id"] == snapshot["job_id"]
    assert api.job(snapshot["job_id"]) == snapshot
