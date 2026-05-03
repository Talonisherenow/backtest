from datetime import date
from pathlib import Path

import pandas as pd

from backtest.core.contracts import BarRequest
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
