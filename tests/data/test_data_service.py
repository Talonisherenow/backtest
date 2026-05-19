from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from backtest.core.contracts import BarRequest, CatalogRecord
from backtest.core.enums import AdjustMode, Frequency
from backtest.core.frames import BAR_COLUMNS
from backtest.data.catalog import DataCatalog
from backtest.data.metadata import MetadataStore
from backtest.data.service import DataSyncService
from backtest.data.store import ParquetBarStore
from backtest.data.tasks import CrawlTaskManager


class FakeProvider:
    def fetch_bars(self, request: BarRequest) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": [request.start_date],
                "symbol": [request.symbols[0]],
                "open": [10.0],
                "high": [11.0],
                "low": [9.8],
                "close": [10.5],
                "volume": [1000],
                "amount": [10500.0],
                "frequency": [request.frequency.value],
                "adjust": [request.adjust.value],
            }
        )


class MultiYearFakeProvider:
    def fetch_bars(self, request: BarRequest) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": [
                    date(2024, 12, 31),
                    date(2025, 1, 2),
                ],
                "symbol": [
                    request.symbols[0],
                    request.symbols[0],
                ],
                "open": [10.0, 10.5],
                "high": [11.0, 11.2],
                "low": [9.8, 10.1],
                "close": [10.5, 10.8],
                "volume": [1000, 1200],
                "amount": [10500.0, 12960.0],
                "frequency": [request.frequency.value, request.frequency.value],
                "adjust": [request.adjust.value, request.adjust.value],
            }
        )


class DateRangeFakeProvider:
    def fetch_bars(self, request: BarRequest) -> pd.DataFrame:
        dates = pd.date_range(request.start_date, request.end_date, freq="D")
        return pd.DataFrame(
            {
                "date": dates,
                "symbol": [request.symbols[0]] * len(dates),
                "open": [10.0] * len(dates),
                "high": [11.0] * len(dates),
                "low": [9.8] * len(dates),
                "close": [10.5] * len(dates),
                "volume": [1000] * len(dates),
                "amount": [10500.0] * len(dates),
                "frequency": [request.frequency.value] * len(dates),
                "adjust": [request.adjust.value] * len(dates),
            }
        )


class EmptyProvider:
    def fetch_bars(self, request: BarRequest) -> pd.DataFrame:
        return pd.DataFrame(columns=BAR_COLUMNS)


class SparseFakeProvider:
    def fetch_bars(self, request: BarRequest) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": [request.start_date, request.end_date],
                "symbol": [request.symbols[0], request.symbols[0]],
                "open": [10.0, 10.0],
                "high": [11.0, 11.0],
                "low": [9.8, 9.8],
                "close": [10.5, 10.5],
                "volume": [1000, 1000],
                "amount": [10500.0, 10500.0],
                "frequency": [request.frequency.value, request.frequency.value],
                "adjust": [request.adjust.value, request.adjust.value],
            }
        )


def test_data_sync_service_fetches_missing_range_and_updates_catalog(tmp_path: Path):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    service = DataSyncService(
        provider=FakeProvider(),
        store=ParquetBarStore(tmp_path / "bars"),
        catalog=DataCatalog(metadata),
        tasks=CrawlTaskManager(metadata),
    )

    service.sync(
        symbols=["000001.SZ"],
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 2),
    )

    assert len(service.catalog.inventory()) == 1
    assert service.tasks.list_tasks()[0].status == "success"


def test_data_sync_service_records_catalog_entries_per_written_partition(
    tmp_path: Path,
):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    store = ParquetBarStore(tmp_path / "bars")
    service = DataSyncService(
        provider=MultiYearFakeProvider(),
        store=store,
        catalog=DataCatalog(metadata),
        tasks=CrawlTaskManager(metadata),
    )

    service.sync(
        symbols=["000001.SZ"],
        start_date=date(2024, 12, 31),
        end_date=date(2025, 1, 2),
    )

    records = service.catalog.inventory()

    assert len(records) == 2
    assert [
        (record.start_date, record.end_date, record.rows, record.cache_path)
        for record in records
    ] == [
        (
            date(2024, 12, 31),
            date(2024, 12, 31),
            1,
            store.partition_path(
                records[0].symbol,
                records[0].frequency,
                records[0].adjust,
                2024,
            ),
        ),
        (
            date(2025, 1, 2),
            date(2025, 1, 2),
            1,
            store.partition_path(
                records[1].symbol,
                records[1].frequency,
                records[1].adjust,
                2025,
            ),
        ),
    ]


def test_data_sync_service_keeps_catalog_coverage_when_appending_same_partition(
    tmp_path: Path,
):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    service = DataSyncService(
        provider=DateRangeFakeProvider(),
        store=ParquetBarStore(tmp_path / "bars"),
        catalog=DataCatalog(metadata),
        tasks=CrawlTaskManager(metadata),
    )

    service.sync(
        symbols=["000001.SZ"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 2),
    )
    service.sync(
        symbols=["000001.SZ"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 4),
    )

    records = service.catalog.inventory()

    assert len(records) == 1
    assert records[0].start_date == date(2025, 1, 1)
    assert records[0].end_date == date(2025, 1, 4)
    assert records[0].rows == 4


def test_data_sync_service_can_refresh_existing_coverage(tmp_path: Path):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    catalog = DataCatalog(metadata)
    catalog.upsert(
        CatalogRecord(
            symbol="BTC/USDT",
            frequency=Frequency.HOUR_1,
            adjust=AdjustMode.NONE,
            start_date=date(2026, 5, 19),
            end_date=date(2026, 5, 19),
            rows=8,
            source="ccxt:bitget",
            cache_path=tmp_path / "existing.parquet",
            updated_at=metadata.now(),
        )
    )
    service = DataSyncService(
        provider=FakeProvider(),
        store=ParquetBarStore(tmp_path / "bars"),
        catalog=catalog,
        tasks=CrawlTaskManager(metadata),
    )

    service.sync(
        symbols=["BTC/USDT"],
        start_date=date(2026, 5, 19),
        end_date=date(2026, 5, 19),
        frequency=Frequency.HOUR_1,
        adjust=AdjustMode.NONE,
        source="ccxt:bitget",
        refresh_existing=True,
    )

    tasks = service.tasks.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].symbol == "BTC/USDT"
    assert tasks[0].status == "success"


def test_data_sync_service_consumes_retrying_tasks_before_creating_missing_tasks(
    tmp_path: Path,
):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    tasks = CrawlTaskManager(metadata)
    task_id = tasks.create_task(
        symbol="000001.SZ",
        frequency=Frequency.DAILY,
        adjust=AdjustMode.QFQ,
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 2),
        source="fixture",
    )
    tasks.mark_running(task_id)
    tasks.mark_failed(task_id, "timeout")
    tasks.mark_retrying(task_id)
    service = DataSyncService(
        provider=FakeProvider(),
        store=ParquetBarStore(tmp_path / "bars"),
        catalog=DataCatalog(metadata),
        tasks=tasks,
    )

    service.sync(
        symbols=["000001.SZ"],
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 2),
        source="fixture",
    )

    records = tasks.list_tasks()
    assert len(records) == 1
    assert records[0].status == "success"
    assert records[0].attempts == 2
    assert records[0].last_error is None
    assert len(service.catalog.inventory()) == 1


def test_data_sync_service_refetches_when_existing_coverage_is_from_other_source(
    tmp_path: Path,
):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    catalog = DataCatalog(metadata)
    catalog.upsert(
        CatalogRecord(
            symbol="000001.SZ",
            frequency=Frequency.DAILY,
            adjust=AdjustMode.QFQ,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 2),
            rows=1,
            source="fixture",
            cache_path=tmp_path / "fixture.parquet",
            updated_at=metadata.now(),
        )
    )
    service = DataSyncService(
        provider=FakeProvider(),
        store=ParquetBarStore(tmp_path / "bars"),
        catalog=catalog,
        tasks=CrawlTaskManager(metadata),
    )

    service.sync(
        symbols=["000001.SZ"],
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 2),
        source="akshare",
    )

    assert sorted(record.source for record in service.catalog.inventory()) == ["akshare", "fixture"]
    assert service.tasks.list_tasks()[0].source == "akshare"


def test_data_sync_service_preserves_other_source_coverage_for_same_partition(
    tmp_path: Path,
):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    service = DataSyncService(
        provider=FakeProvider(),
        store=ParquetBarStore(tmp_path / "bars"),
        catalog=DataCatalog(metadata),
        tasks=CrawlTaskManager(metadata),
    )

    service.sync(
        symbols=["000001.SZ"],
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 2),
        source="fixture",
    )
    service.sync(
        symbols=["000001.SZ"],
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 2),
        source="akshare",
    )

    assert sorted(record.source for record in service.catalog.inventory()) == ["akshare", "fixture"]
    assert service.catalog.missing_ranges(
        symbols=["000001.SZ"],
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 2),
        frequency=Frequency.DAILY,
        adjust=AdjustMode.QFQ,
        source="fixture",
    ) == []


def test_data_sync_service_marks_empty_provider_results_failed(tmp_path: Path):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    service = DataSyncService(
        provider=EmptyProvider(),
        store=ParquetBarStore(tmp_path / "bars"),
        catalog=DataCatalog(metadata),
        tasks=CrawlTaskManager(metadata),
    )

    with pytest.raises(ValueError, match="No bar data returned"):
        service.sync(
            symbols=["000001.SZ"],
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 2),
            source="fixture",
        )

    assert service.catalog.inventory() == []
    task = service.tasks.list_tasks()[0]
    assert task.status == "failed"
    assert "No bar data returned" in task.last_error


def test_data_sync_service_catalogs_sparse_results_as_missing_inner_ranges(
    tmp_path: Path,
):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    service = DataSyncService(
        provider=SparseFakeProvider(),
        store=ParquetBarStore(tmp_path / "bars"),
        catalog=DataCatalog(metadata),
        tasks=CrawlTaskManager(metadata),
    )

    service.sync(
        symbols=["000001.SZ"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 4),
        source="fixture",
    )

    assert [
        (record.start_date, record.end_date, record.rows)
        for record in service.catalog.inventory()
    ] == [
        (date(2025, 1, 1), date(2025, 1, 1), 1),
        (date(2025, 1, 4), date(2025, 1, 4), 1),
    ]
    assert service.catalog.missing_ranges(
        symbols=["000001.SZ"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 4),
        frequency=Frequency.DAILY,
        adjust=AdjustMode.QFQ,
        source="fixture",
    ) == [("000001.SZ", date(2025, 1, 2), date(2025, 1, 3))]
