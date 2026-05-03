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
