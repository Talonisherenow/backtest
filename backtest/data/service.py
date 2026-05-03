from datetime import date

import pandas as pd

from backtest.core.contracts import BarRequest, CatalogRecord
from backtest.core.enums import AdjustMode, Frequency
from backtest.core.symbols import normalize_symbol
from backtest.data.catalog import DataCatalog
from backtest.data.provider import DataProvider
from backtest.data.store import ParquetBarStore
from backtest.data.tasks import CrawlTaskManager


class DataSyncService:
    def __init__(
        self,
        provider: DataProvider,
        store: ParquetBarStore,
        catalog: DataCatalog,
        tasks: CrawlTaskManager,
    ) -> None:
        self.provider = provider
        self.store = store
        self.catalog = catalog
        self.tasks = tasks

    def sync(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        frequency: Frequency = Frequency.DAILY,
        adjust: AdjustMode = AdjustMode.QFQ,
        source: str = "akshare",
    ) -> None:
        normalized_symbols = [normalize_symbol(symbol) for symbol in symbols]
        missing = self.catalog.missing_ranges(
            normalized_symbols,
            start_date,
            end_date,
            frequency,
            adjust,
        )
        for symbol, missing_start, missing_end in missing:
            task_id = self.tasks.create_task(
                symbol,
                frequency,
                adjust,
                missing_start,
                missing_end,
                source,
            )
            self.tasks.mark_running(task_id)
            try:
                bars = self.provider.fetch_bars(
                    BarRequest(
                        symbols=[symbol],
                        start_date=missing_start,
                        end_date=missing_end,
                        frequency=frequency,
                        adjust=adjust,
                        source=source,
                    )
                )
                written = self.store.write_bars(bars)
                if not bars.empty:
                    dates = pd.to_datetime(bars["date"])
                    self.catalog.upsert(
                        CatalogRecord(
                            symbol=symbol,
                            frequency=frequency,
                            adjust=adjust,
                            start_date=dates.min().date(),
                            end_date=dates.max().date(),
                            rows=len(bars),
                            source=source,
                            cache_path=written[0],
                            updated_at=self.catalog.metadata.now(),
                        )
                    )
                self.tasks.mark_success(task_id)
            except Exception as exc:
                self.tasks.mark_failed(task_id, str(exc))
                raise
