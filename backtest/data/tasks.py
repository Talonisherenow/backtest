from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from backtest.core.contracts import CrawlTaskRecord
from backtest.core.enums import AdjustMode, Frequency
from backtest.data.metadata import MetadataStore


@dataclass(frozen=True)
class CrawlTaskSummary:
    total: int
    status_counts: dict[str, int]
    frequency_counts: dict[str, int]
    latest_updated_at: datetime | None


@dataclass(frozen=True)
class CrawlTaskPage:
    tasks: list[CrawlTaskRecord]
    page: int
    page_size: int
    total: int
    total_pages: int


@dataclass(frozen=True)
class CrawlTaskPurgeResult:
    deleted: int
    retained: int
    cutoff: datetime
    vacuumed: bool


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

    def task_summary(self) -> CrawlTaskSummary:
        with self.metadata.connect() as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) AS total, MAX(updated_at) AS latest_updated_at FROM crawl_tasks"
            ).fetchone()
            status_rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM crawl_tasks GROUP BY status"
            ).fetchall()
            frequency_rows = conn.execute(
                "SELECT frequency, COUNT(*) AS count FROM crawl_tasks GROUP BY frequency"
            ).fetchall()

        latest_updated_at = total_row["latest_updated_at"] if total_row else None
        return CrawlTaskSummary(
            total=int(total_row["total"] if total_row else 0),
            status_counts={row["status"]: int(row["count"]) for row in status_rows},
            frequency_counts={row["frequency"]: int(row["count"]) for row in frequency_rows},
            latest_updated_at=self._parse_dt(latest_updated_at),
        )

    def purge_older_than(
        self,
        *,
        retain_days: int,
        vacuum: bool = False,
        now: datetime | None = None,
    ) -> CrawlTaskPurgeResult:
        if retain_days < 1:
            raise ValueError("retain_days must be greater than or equal to 1")
        anchor = now or self.metadata.now()
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        else:
            anchor = anchor.astimezone(timezone.utc)
        cutoff = anchor - timedelta(days=retain_days)
        cutoff_text = cutoff.isoformat()

        with self.metadata.connect() as conn:
            deleted = conn.execute(
                "DELETE FROM crawl_tasks WHERE created_at < ?",
                (cutoff_text,),
            ).rowcount
            retained = int(
                conn.execute("SELECT COUNT(*) AS total FROM crawl_tasks").fetchone()["total"]
            )

        vacuumed = False
        if vacuum:
            import sqlite3

            vacuum_conn = sqlite3.connect(self.metadata.path, timeout=60.0)
            try:
                vacuum_conn.execute("VACUUM")
            finally:
                vacuum_conn.close()
            vacuumed = True

        return CrawlTaskPurgeResult(
            deleted=max(int(deleted), 0),
            retained=retained,
            cutoff=cutoff,
            vacuumed=vacuumed,
        )

    def list_tasks_page(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        symbol: str | None = None,
        frequencies: list[Frequency] | None = None,
        statuses: list[str] | None = None,
    ) -> CrawlTaskPage:
        if page < 1:
            raise ValueError("page must be greater than or equal to 1")
        if page_size < 1:
            raise ValueError("page_size must be greater than or equal to 1")
        capped_page_size = min(page_size, 100)
        where_sql, params = self._task_filter_sql(
            symbol=symbol,
            frequencies=frequencies,
            statuses=statuses,
        )
        offset = (page - 1) * capped_page_size

        with self.metadata.connect() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS total FROM crawl_tasks{where_sql}",
                params,
            ).fetchone()
            rows = conn.execute(
                f"""
                SELECT *
                FROM crawl_tasks
                {where_sql}
                ORDER BY updated_at DESC, task_id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, capped_page_size, offset],
            ).fetchall()

        total = int(total_row["total"] if total_row else 0)
        total_pages = max(1, (total + capped_page_size - 1) // capped_page_size)
        return CrawlTaskPage(
            tasks=[self._record_from_row(row) for row in rows],
            page=page,
            page_size=capped_page_size,
            total=total,
            total_pages=total_pages,
        )

    def _task_filter_sql(
        self,
        *,
        symbol: str | None,
        frequencies: list[Frequency] | None,
        statuses: list[str] | None,
    ) -> tuple[str, list[str]]:
        clauses: list[str] = []
        params: list[str] = []
        if symbol:
            clauses.append("LOWER(symbol) LIKE ?")
            params.append(f"%{symbol.lower()}%")
        if frequencies:
            placeholders = ", ".join("?" for _ in frequencies)
            clauses.append(f"frequency IN ({placeholders})")
            params.extend(frequency.value for frequency in frequencies)
        if statuses:
            normalized_statuses = [status.strip() for status in statuses if status.strip()]
            if normalized_statuses:
                placeholders = ", ".join("?" for _ in normalized_statuses)
                clauses.append(f"status IN ({placeholders})")
                params.extend(normalized_statuses)
        if not clauses:
            return "", params
        return " WHERE " + " AND ".join(clauses), params

    def _record_from_row(self, row) -> CrawlTaskRecord:
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
            created_at=self._parse_dt(row["created_at"]),
            updated_at=self._parse_dt(row["updated_at"]),
            started_at=self._parse_dt(row["started_at"]),
            finished_at=self._parse_dt(row["finished_at"]),
        )

    @staticmethod
    def _parse_dt(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None
