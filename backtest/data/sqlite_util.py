from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def open_sqlite_connection(
    path: str | Path,
    *,
    enable_foreign_keys: bool = False,
) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection that is always closed on context exit.

    ``sqlite3.Connection`` as a context manager only commits/rollbacks; it does
    **not** close the underlying file descriptors. Callers must use this helper
    (or an equivalent ``finally: conn.close()``) to avoid FD leaks under
    ThreadingHTTPServer load.
    """
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    if enable_foreign_keys:
        conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
