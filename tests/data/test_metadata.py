import sqlite3
from pathlib import Path

import pytest

from backtest.data.metadata import MetadataStore


def test_connect_closes_sqlite_connection_after_context_exit(tmp_path: Path):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")

    with metadata.connect() as conn:
        conn.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")
