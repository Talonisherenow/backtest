from pathlib import Path

from backtest.data.metadata import MetadataStore


def test_metadata_store_enables_wal_and_busy_timeout(tmp_path: Path):
    store = MetadataStore(tmp_path / "metadata.sqlite")

    with store.connect() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]

    assert str(journal_mode).lower() == "wal"
    assert int(busy_timeout) >= 30000
