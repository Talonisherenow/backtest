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


def test_parquet_store_deduplicates_new_partition_writes_keeping_last(
    tmp_path: Path,
):
    store = ParquetBarStore(tmp_path / "bars")
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-02"]),
            "symbol": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 10.5],
            "high": [11.0, 11.5],
            "low": [9.8, 10.1],
            "close": [10.5, 11.0],
            "volume": [1000, 1200],
            "amount": [10500.0, 13200.0],
            "frequency": ["1d", "1d"],
            "adjust": ["qfq", "qfq"],
        }
    )

    store.write_bars(bars)
    loaded = store.read_bars(
        symbols=["000001.SZ"],
        start_date=pd.Timestamp("2025-01-02").date(),
        end_date=pd.Timestamp("2025-01-02").date(),
        frequency=Frequency.DAILY,
        adjust=AdjustMode.QFQ,
    )

    assert len(loaded) == 1
    assert loaded.loc[0, "close"] == 11.0


def test_parquet_store_encodes_crypto_symbol_paths_and_reads_full_intraday_end_date(
    tmp_path: Path,
):
    store = ParquetBarStore(tmp_path / "bars")
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2025-01-02 00:00:00",
                    "2025-01-02 04:00:00",
                    "2025-01-02 08:00:00",
                ]
            ),
            "symbol": ["BTC/USDT", "BTC/USDT", "BTC/USDT"],
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "volume": [1.0, 2.0, 3.0],
            "amount": [100.5, 203.0, 307.5],
            "frequency": ["4h", "4h", "4h"],
            "adjust": ["none", "none", "none"],
        }
    )

    written = store.write_bars(bars)
    loaded = store.read_bars(
        symbols=["BTC/USDT"],
        start_date=pd.Timestamp("2025-01-02").date(),
        end_date=pd.Timestamp("2025-01-02").date(),
        frequency=Frequency.HOUR_4,
        adjust=AdjustMode.NONE,
    )

    assert written
    assert "symbol=BTC%2FUSDT" in written[0].parts
    assert len(loaded) == 3
    assert loaded["symbol"].unique().tolist() == ["BTC/USDT"]
