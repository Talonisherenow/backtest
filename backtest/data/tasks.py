from datetime import date, datetime

from backtest.core.contracts import CrawlTaskRecord
from backtest.core.enums import AdjustMode, Frequency
from backtest.data.metadata import MetadataStore


class CrawlTaskManager:
    def __init__(self, metadata: MetadataStore) -> None:
        self.metadata = metadata

    def create_task(
        self,
        symbol: str,
        frequency: Frequency,
        adjust: AdjustMode,
        start_date: date,
        end_date: date,
        source: str,
    ) -> int:
        now = self.metadata.now().isoformat()
        with self.metadata.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO crawl_tasks
                (symbol, frequency, adjust, start_date, end_date, source, status, attempts, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)
                """,
                (symbol, frequency.value, adjust.value, start_date.isoformat(), end_date.isoformat(), source, now, now),
            )
            return int(cursor.lastrowid)

    def mark_running(self, task_id: int) -> None:
        now = self.metadata.now().isoformat()
        with self.metadata.connect() as conn:
            conn.execute(
                """
                UPDATE crawl_tasks
                SET status = 'running', attempts = attempts + 1, updated_at = ?, started_at = ?
                WHERE task_id = ?
                """,
                (now, now, task_id),
            )

    def mark_success(self, task_id: int) -> None:
        now = self.metadata.now().isoformat()
        with self.metadata.connect() as conn:
            conn.execute(
                """
                UPDATE crawl_tasks
                SET status = 'success', updated_at = ?, finished_at = ?, last_error = NULL
                WHERE task_id = ?
                """,
                (now, now, task_id),
            )

    def mark_failed(self, task_id: int, error: str) -> None:
        now = self.metadata.now().isoformat()
        with self.metadata.connect() as conn:
            conn.execute(
                """
                UPDATE crawl_tasks
                SET status = 'failed', updated_at = ?, finished_at = ?, last_error = ?
                WHERE task_id = ?
                """,
                (now, now, error, task_id),
            )

    def mark_retrying(self, task_id: int) -> None:
        now = self.metadata.now().isoformat()
        with self.metadata.connect() as conn:
            conn.execute(
                """
                UPDATE crawl_tasks
                SET status = 'retrying', updated_at = ?, last_error = NULL
                WHERE task_id = ?
                """,
                (now, task_id),
            )

    def failed_tasks(self) -> list[CrawlTaskRecord]:
        with self.metadata.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM crawl_tasks WHERE status = 'failed' ORDER BY updated_at"
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def retrying_tasks(self) -> list[CrawlTaskRecord]:
        with self.metadata.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM crawl_tasks WHERE status = 'retrying' ORDER BY updated_at"
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def list_tasks(self) -> list[CrawlTaskRecord]:
        with self.metadata.connect() as conn:
            rows = conn.execute("SELECT * FROM crawl_tasks ORDER BY created_at").fetchall()
        return [self._record_from_row(row) for row in rows]

    def _record_from_row(self, row) -> CrawlTaskRecord:
        parse_dt = lambda value: datetime.fromisoformat(value) if value else None
        return CrawlTaskRecord(
            task_id=row["task_id"],
            symbol=row["symbol"],
            frequency=Frequency(row["frequency"]),
            adjust=AdjustMode(row["adjust"]),
            start_date=date.fromisoformat(row["start_date"]),
            end_date=date.fromisoformat(row["end_date"]),
            source=row["source"],
            status=row["status"],
            attempts=row["attempts"],
            last_error=row["last_error"],
            created_at=parse_dt(row["created_at"]),
            updated_at=parse_dt(row["updated_at"]),
            started_at=parse_dt(row["started_at"]),
            finished_at=parse_dt(row["finished_at"]),
        )
