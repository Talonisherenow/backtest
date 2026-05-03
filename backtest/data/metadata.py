import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class MetadataStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _init_schema(self) -> None:
        with self.connect() as conn:
            self._init_catalog_schema(conn)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS crawl_tasks (
                    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    frequency TEXT NOT NULL,
                    adjust TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
                """
            )

    def _init_catalog_schema(self, conn: sqlite3.Connection) -> None:
        desired_pk = [
            "symbol",
            "frequency",
            "adjust",
            "start_date",
            "end_date",
            "cache_path",
        ]
        if (
            self._table_exists(conn, "catalog")
            and self._primary_key_columns(conn, "catalog") != desired_pk
        ):
            conn.execute("ALTER TABLE catalog RENAME TO catalog_old")
            self._create_catalog_table(conn)
            conn.execute(
                """
                INSERT OR IGNORE INTO catalog
                (symbol, frequency, adjust, start_date, end_date, rows, source, cache_path, updated_at, quality_status)
                SELECT
                    symbol,
                    frequency,
                    adjust,
                    start_date,
                    end_date,
                    rows,
                    source,
                    cache_path,
                    updated_at,
                    quality_status
                FROM catalog_old
                """
            )
            conn.execute("DROP TABLE catalog_old")
            return

        self._create_catalog_table(conn)

    def _create_catalog_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog (
                symbol TEXT NOT NULL,
                frequency TEXT NOT NULL,
                adjust TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                rows INTEGER NOT NULL,
                source TEXT NOT NULL,
                cache_path TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                quality_status TEXT NOT NULL,
                PRIMARY KEY (symbol, frequency, adjust, start_date, end_date, cache_path)
            )
            """
        )

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _primary_key_columns(self, conn: sqlite3.Connection, table_name: str) -> list[str]:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [row["name"] for row in sorted(rows, key=lambda row: row["pk"]) if row["pk"]]
