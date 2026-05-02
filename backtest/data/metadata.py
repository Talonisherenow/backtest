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
                    PRIMARY KEY (symbol, frequency, adjust, cache_path)
                )
                """
            )
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
