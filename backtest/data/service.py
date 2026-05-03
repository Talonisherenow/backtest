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
            source=source,
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
            if validated.empty:
                raise ValueError(f"No bar data returned for {symbol} from {start_date} to {end_date}")
            written = self.store.write_bars(validated)
            if not written:
                raise ValueError(f"No bar data written for {symbol} from {start_date} to {end_date}")
            for path in written:
                partition = validate_bar_frame(pd.read_parquet(path))
                for (
                    partition_symbol,
                    partition_frequency,
                    partition_adjust,
                ), group in partition.groupby(["symbol", "frequency", "adjust"]):
                    record_frequency = Frequency(partition_frequency)
                    record_adjust = AdjustMode(partition_adjust)
                    self.catalog.delete_cache_path(
                        partition_symbol,
                        record_frequency,
                        record_adjust,
                        path,
                    )
                    for segment_start, segment_end, rows in self._coverage_segments(group):
                        self.catalog.upsert(
                            CatalogRecord(
                                symbol=partition_symbol,
                                frequency=record_frequency,
                                adjust=record_adjust,
                                start_date=segment_start,
                                end_date=segment_end,
                                rows=rows,
                                source=source,
                                cache_path=path,
                                updated_at=self.catalog.metadata.now(),
                            )
                        )
            self.tasks.mark_success(task_id)
        except Exception as exc:
            self.tasks.mark_failed(task_id, str(exc))
            raise

    def _coverage_segments(self, group: pd.DataFrame) -> list[tuple[date, date, int]]:
        dates = pd.to_datetime(group["date"]).dt.normalize().drop_duplicates().sort_values().tolist()
        if not dates:
            return []

        segments: list[tuple[date, date, int]] = []
        segment_start = dates[0]
        previous = dates[0]
        rows = 1
        for current in dates[1:]:
            next_business_day = previous + pd.offsets.BDay(1)
            if current <= next_business_day:
                previous = current
                rows += 1
                continue
            segments.append((segment_start.date(), previous.date(), rows))
            segment_start = current
            previous = current
            rows = 1
        segments.append((segment_start.date(), previous.date(), rows))
        return segments
