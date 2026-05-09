from pathlib import Path

import pandas as pd

from backtest.charts.kline_service import KlineCacheService
from backtest.data.store import ParquetBarStore


def _write_cached_bars(
    bars_root: Path,
    symbol: str,
    *,
    frequency: str = "1d",
    adjust: str = "none",
    dates: list[str] | None = None,
) -> None:
    dates = dates or [f"2025-01-{day:02d}" for day in range(1, 11)]
    rows = len(dates)
    ParquetBarStore(bars_root).write_bars(
        pd.DataFrame(
            {
                "date": pd.to_datetime(dates),
                "symbol": [symbol] * rows,
                "open": [float(index + 10) for index in range(rows)],
                "high": [float(index + 11) for index in range(rows)],
                "low": [float(index + 9) for index in range(rows)],
                "close": [float(index + 10.5) for index in range(rows)],
                "volume": [1000 + index for index in range(rows)],
                "amount": [10000.0 + index for index in range(rows)],
                "frequency": [frequency] * rows,
                "adjust": [adjust] * rows,
            }
        )
    )


def test_kline_cache_service_manifest_indexes_cached_series_without_bars(tmp_path: Path):
    bars_root = tmp_path / "bars"
    _write_cached_bars(bars_root, "BTC/USDT", frequency="1d")
    _write_cached_bars(
        bars_root,
        "BTC/USDT",
        frequency="4h",
        dates=[
            "2025-01-01 00:00:00",
            "2025-01-01 04:00:00",
            "2025-01-01 08:00:00",
        ],
    )

    manifest = KlineCacheService(bars_root=bars_root, adjust="none").manifest()

    source = manifest["sources"][0]
    assert source["source_id"] == "default"
    assert source["frequencies"] == ["4h", "1d"]
    item = source["symbols"][0]
    assert item["symbol"] == "BTC/USDT"
    assert item["exchange"] == "Crypto"
    assert item["board"] == "Spot"
    assert "bars" not in item["series"][0]
    assert item["series"][0]["rows"] == 3
    assert item["series"][0]["first_bar"] == "2025-01-01T00:00:00"


def test_kline_cache_service_reads_latest_and_offset_windows(tmp_path: Path):
    bars_root = tmp_path / "bars"
    _write_cached_bars(bars_root, "BTC/USDT")
    service = KlineCacheService(bars_root=bars_root, adjust="none")

    latest = service.bars(symbol="BTC/USDT", frequency="1d", limit=3, anchor="latest")
    page = service.bars(symbol="BTC/USDT", frequency="1d", limit=3, offset=2)

    assert latest["rows"] == 10
    assert latest["offset"] == 7
    assert latest["start_row"] == 8
    assert latest["end_row"] == 10
    assert [bar["date"] for bar in latest["bars"]] == [
        "2025-01-08",
        "2025-01-09",
        "2025-01-10",
    ]
    assert page["offset"] == 2
    assert page["start_row"] == 3
    assert page["end_row"] == 5
    assert [bar["date"] for bar in page["bars"]] == [
        "2025-01-03",
        "2025-01-04",
        "2025-01-05",
    ]


def test_kline_cache_service_jumps_to_start_time(tmp_path: Path):
    bars_root = tmp_path / "bars"
    _write_cached_bars(bars_root, "BTC/USDT")

    result = KlineCacheService(bars_root=bars_root, adjust="none").bars(
        symbol="BTC/USDT",
        frequency="1d",
        limit=3,
        start="2025-01-05",
    )

    assert result["offset"] == 4
    assert result["start_row"] == 5
    assert result["bars"][0]["date"] == "2025-01-05"


def test_kline_cache_service_jumps_to_containing_bar_start(tmp_path: Path):
    bars_root = tmp_path / "bars"
    _write_cached_bars(
        bars_root,
        "BTC/USDT",
        frequency="5m",
        dates=[
            "2025-01-01 10:00:00",
            "2025-01-01 10:05:00",
            "2025-01-01 10:10:00",
        ],
    )

    result = KlineCacheService(bars_root=bars_root, adjust="none").bars(
        symbol="BTC/USDT",
        frequency="5m",
        limit=2,
        start="2025-01-01T10:02",
    )

    assert result["offset"] == 0
    assert result["bars"][0]["date"] == "2025-01-01T10:00:00"


def test_kline_cache_service_clamps_time_jump_to_last_full_window(tmp_path: Path):
    bars_root = tmp_path / "bars"
    _write_cached_bars(
        bars_root,
        "BTC/USDT",
        frequency="5m",
        dates=[
            "2025-01-01 10:00:00",
            "2025-01-01 10:05:00",
            "2025-01-01 10:10:00",
            "2025-01-01 10:15:00",
            "2025-01-01 10:20:00",
        ],
    )

    result = KlineCacheService(bars_root=bars_root, adjust="none").bars(
        symbol="BTC/USDT",
        frequency="5m",
        limit=3,
        start="2025-01-01T10:17",
    )

    assert result["offset"] == 2
    assert result["bars"][0]["date"] == "2025-01-01T10:10:00"
    assert result["bars"][-1]["date"] == "2025-01-01T10:20:00"


def test_kline_cache_service_supports_multiple_source_roots(tmp_path: Path):
    bitget_root = tmp_path / "bitget" / "bars"
    binance_root = tmp_path / "binance" / "bars"
    _write_cached_bars(bitget_root, "BTC/USDT")
    _write_cached_bars(binance_root, "ETH/USDT")

    service = KlineCacheService(
        bars_root=bitget_root,
        source_roots=[("bitget", bitget_root), ("binance", binance_root)],
        adjust="none",
    )

    manifest = service.manifest()
    result = service.bars(
        source_id="binance",
        symbol="ETH/USDT",
        frequency="1d",
        limit=2,
        anchor="latest",
    )

    assert [source["source_id"] for source in manifest["sources"]] == ["bitget", "binance"]
    assert manifest["sources"][1]["source_label"] == "Binance"
    assert result["source_id"] == "binance"
    assert result["symbol"] == "ETH/USDT"
    assert [bar["date"] for bar in result["bars"]] == ["2025-01-09", "2025-01-10"]
