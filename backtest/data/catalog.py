from datetime import date, datetime
from pathlib import Path

from backtest.core.contracts import CatalogRecord
from backtest.core.enums import AdjustMode, Frequency
from backtest.data.metadata import MetadataStore


class DataCatalog:
    def __init__(self, metadata: MetadataStore) -> None:
        self.metadata = metadata

    def upsert(self, record: CatalogRecord) -> None:
        with self.metadata.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO catalog
                (symbol, frequency, adjust, start_date, end_date, rows, source, cache_path, updated_at, quality_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.symbol,
                    record.frequency.value,
                    record.adjust.value,
                    record.start_date.isoformat(),
                    record.end_date.isoformat(),
                    record.rows,
                    record.source,
                    str(record.cache_path),
                    record.updated_at.isoformat(),
                    record.quality_status,
                ),
            )

    def inventory(self) -> list[CatalogRecord]:
        with self.metadata.connect() as conn:
            rows = conn.execute("SELECT * FROM catalog ORDER BY symbol, start_date").fetchall()
        return [self._record_from_row(row) for row in rows]

    def coverage(self, symbol: str, frequency: Frequency, adjust: AdjustMode) -> list[CatalogRecord]:
        with self.metadata.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM catalog
                WHERE symbol = ? AND frequency = ? AND adjust = ?
                ORDER BY start_date
                """,
                (symbol, frequency.value, adjust.value),
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def missing_ranges(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        frequency: Frequency,
        adjust: AdjustMode,
    ) -> list[tuple[str, date, date]]:
        missing: list[tuple[str, date, date]] = []
        for symbol in symbols:
            ranges = [(record.start_date, record.end_date) for record in self.coverage(symbol, frequency, adjust)]
            if not ranges:
                missing.append((symbol, start_date, end_date))
                continue
            ranges.sort()
            cursor = start_date
            for covered_start, covered_end in ranges:
                if covered_end < cursor:
                    continue
                if covered_start > cursor:
                    missing.append((symbol, cursor, covered_start.fromordinal(covered_start.toordinal() - 1)))
                if covered_end >= cursor:
                    cursor = covered_end.fromordinal(covered_end.toordinal() + 1)
                if cursor > end_date:
                    break
            if cursor <= end_date:
                missing.append((symbol, cursor, end_date))
        return missing

    def _record_from_row(self, row) -> CatalogRecord:
        return CatalogRecord(
            symbol=row["symbol"],
            frequency=Frequency(row["frequency"]),
            adjust=AdjustMode(row["adjust"]),
            start_date=date.fromisoformat(row["start_date"]),
            end_date=date.fromisoformat(row["end_date"]),
            rows=row["rows"],
            source=row["source"],
            cache_path=Path(row["cache_path"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            quality_status=row["quality_status"],
        )
