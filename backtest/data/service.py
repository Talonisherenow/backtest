from datetime import date

import pandas as pd

from backtest.core.contracts import BarRequest, CatalogRecord, CrawlTaskRecord
from backtest.core.enums import AdjustMode, Frequency
from backtest.core.frames import validate_bar_frame
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
        self._sync_retrying_tasks(
            normalized_symbols,
            start_date,
            end_date,
            frequency,
            adjust,
            source,
        )
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
            self._execute_task(
                task_id,
                symbol,
                missing_start,
                missing_end,
                frequency,
                adjust,
                source,
            )

    def _sync_retrying_tasks(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        frequency: Frequency,
        adjust: AdjustMode,
        source: str,
    ) -> None:
        for task in self.tasks.retrying_tasks():
            if task.task_id is None:
                continue
            if self._task_matches_request(
                task,
                symbols,
                start_date,
                end_date,
                frequency,
                adjust,
                source,
            ):
                self._execute_task(
                    task.task_id,
                    task.symbol,
                    task.start_date,
                    task.end_date,
                    task.frequency,
                    task.adjust,
                    task.source,
                )

    def _task_matches_request(
        self,
        task: CrawlTaskRecord,
        symbols: list[str],
        start_date: date,
        end_date: date,
        frequency: Frequency,
        adjust: AdjustMode,
        source: str,
    ) -> bool:
        return (
            task.symbol in symbols
            and task.frequency == frequency
            and task.adjust == adjust
            and task.source == source
            and task.start_date >= start_date
            and task.end_date <= end_date
        )

    def _execute_task(
        self,
        task_id: int,
        symbol: str,
        start_date: date,
        end_date: date,
        frequency: Frequency,
        adjust: AdjustMode,
        source: str,
    ) -> None:
        self.tasks.mark_running(task_id)
        try:
            bars = self.provider.fetch_bars(
                BarRequest(
                    symbols=[symbol],
                    start_date=start_date,
                    end_date=end_date,
                    frequency=frequency,
                    adjust=adjust,
                    source=source,
                )
            )
            validated = validate_bar_frame(bars)
            written = self.store.write_bars(validated)
            for path in written:
                partition = validate_bar_frame(pd.read_parquet(path))
                for (
                    partition_symbol,
                    partition_frequency,
                    partition_adjust,
                ), group in partition.groupby(["symbol", "frequency", "adjust"]):
                    partition_dates = pd.to_datetime(group["date"])
                    self.catalog.upsert(
                        CatalogRecord(
                            symbol=partition_symbol,
                            frequency=Frequency(partition_frequency),
                            adjust=AdjustMode(partition_adjust),
                            start_date=partition_dates.min().date(),
                            end_date=partition_dates.max().date(),
                            rows=len(group),
                            source=source,
                            cache_path=path,
                            updated_at=self.catalog.metadata.now(),
                        )
                    )
            self.tasks.mark_success(task_id)
        except Exception as exc:
            self.tasks.mark_failed(task_id, str(exc))
            raise
