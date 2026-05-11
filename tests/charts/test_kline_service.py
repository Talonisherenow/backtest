from pathlib import Path

import pandas as pd

from backtest.charts.kline_service import KlineCacheService, KlineSource


def _write_bars(
    root: Path,
    *,
    symbol_dir: str,
    symbol: str,
    frequency: str,
    adjust: str,
    dates: list[str],
) -> None:
    path = root / f"frequency={frequency}" / f"adjust={adjust}" / f"symbol={symbol_dir}" / "year=2025" / "bars.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "symbol": [symbol] * len(dates),
            "open": [10.0 + index for index in range(len(dates))],
            "high": [11.0 + index for index in range(len(dates))],
            "low": [9.0 + index for index in range(len(dates))],
            "close": [10.5 + index for index in range(len(dates))],
            "volume": [1000 + index for index in range(len(dates))],
            "amount": [10500.0 + index for index in range(len(dates))],
            "frequency": [frequency] * len(dates),
            "adjust": [adjust] * len(dates),
        }
    ).to_parquet(path, index=False)


def test_kline_cache_service_exposes_bitget_and_a_share_sources(tmp_path: Path) -> None:
    crypto_root = tmp_path / "crypto" / "bitget" / "bars"
    a_share_root = tmp_path / "bars"
    universe_path = tmp_path / "a_share_all.csv"
    universe_path.write_text(
        "symbol,code,name,exchange,board,list_date,industry\n"
        "000001.SZ,000001,平安银行,SZ,主板,1991-04-03,J 金融业\n",
        encoding="utf-8",
    )
    _write_bars(
        crypto_root,
        symbol_dir="BTC%2FUSDT",
        symbol="BTC/USDT",
        frequency="1h",
        adjust="none",
        dates=["2025-01-02 09:00:00", "2025-01-02 10:00:00", "2025-01-02 11:00:00"],
    )
    _write_bars(
        a_share_root,
        symbol_dir="000001.SZ",
        symbol="000001.SZ",
        frequency="1d",
        adjust="qfq",
        dates=["2025-01-02", "2025-01-03", "2025-01-06"],
    )

    service = KlineCacheService(
        sources=[
            KlineSource("bitget", "Bitget", crypto_root, adjust="none"),
            KlineSource("a_share", "A-share", a_share_root, adjust="qfq", universe_path=universe_path),
        ]
    )

    manifest = service.manifest(default_window_size=300)

    assert manifest["mode"] == "dynamic"
    assert [source["source_id"] for source in manifest["sources"]] == ["bitget", "a_share"]
    assert manifest["sources"][0]["frequencies"] == ["1h"]
    a_share_symbol = manifest["sources"][1]["symbols"][0]
    assert a_share_symbol["symbol"] == "000001.SZ"
    assert a_share_symbol["name"] == "平安银行"
    assert a_share_symbol["exchange"] == "SZ"
    assert a_share_symbol["board"] == "主板"
    assert a_share_symbol["series"][0]["rows"] == 3
    assert a_share_symbol["series"][0]["first_bar"] == "2025-01-02"
    assert a_share_symbol["series"][0]["last_bar"] == "2025-01-06"
    assert a_share_symbol["series"][0]["years"] == [2025]

    a_share_window = service.bars(
        source_id="a_share",
        symbol="000001.SZ",
        frequency="1d",
        adjust="qfq",
        limit=2,
        anchor="latest",
    )
    crypto_window = service.bars(
        source_id="bitget",
        symbol="BTC/USDT",
        frequency="1h",
        adjust="none",
        limit=2,
        anchor="latest",
    )

    assert [bar["date"] for bar in a_share_window["bars"]] == ["2025-01-03", "2025-01-06"]
    assert a_share_window["rows"] == 3
    assert a_share_window["offset"] == 1
    assert [bar["date"] for bar in crypto_window["bars"]] == [
        "2025-01-02T10:00:00",
        "2025-01-02T11:00:00",
    ]
