from pathlib import Path

import pandas as pd

from backtest.core.enums import AdjustMode, Frequency
from backtest.data.store import ParquetBarStore


def test_parquet_store_writes_partitioned_bars_and_reads_range(tmp_path: Path):
    store = ParquetBarStore(tmp_path / "bars")
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "symbol": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 10.5],
            "high": [11.0, 11.2],
            "low": [9.8, 10.1],
            "close": [10.5, 10.8],
            "volume": [1000, 1200],
            "amount": [10500.0, 12960.0],
            "frequency": ["1d", "1d"],
            "adjust": ["qfq", "qfq"],
        }
    )

    written = store.write_bars(bars)
    loaded = store.read_bars(
        symbols=["000001.SZ"],
        start_date=pd.Timestamp("2025-01-02").date(),
        end_date=pd.Timestamp("2025-01-03").date(),
        frequency=Frequency.DAILY,
        adjust=AdjustMode.QFQ,
    )

    assert written
    assert len(loaded) == 2
    assert loaded["close"].tolist() == [10.5, 10.8]
