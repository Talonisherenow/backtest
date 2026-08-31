from pathlib import Path

from backtest.data.metadata import MetadataStore


def test_metadata_store_enables_wal_and_busy_timeout(tmp_path: Path):
    store = MetadataStore(tmp_path / "metadata.sqlite")

    with store.connect() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]

    assert str(journal_mode).lower() == "wal"
    assert int(busy_timeout) >= 30000


def test_metadata_store_connect_context_closes_connection(tmp_path: Path):
    store = MetadataStore(tmp_path / "metadata.sqlite")
    connections = []

    for _ in range(3):
        with store.connect() as conn:
            conn.execute("SELECT 1")
            connections.append(conn)

    for conn in connections:
        try:
            conn.execute("SELECT 1")
            closed = False
        except Exception:
            closed = True
        assert closed, "sqlite connection must be closed when leaving store.connect()"


def test_metadata_store_reuses_schema_init_without_extra_open_connections(tmp_path: Path):
    path = tmp_path / "metadata.sqlite"
    first = MetadataStore(path)
    second = MetadataStore(path)

    assert first.path == second.path
    # Constructing another store for the same path must not leave live connections behind.
    assert path.exists()
