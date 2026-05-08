from pathlib import Path

import pandas as pd

from backtest.charts.kline_viewer import build_kline_payload, write_kline_viewer
from backtest.data.store import ParquetBarStore


def _write_cached_bars(
    bars_root: Path,
    symbol: str,
    *,
    frequency: str = "1d",
    adjust: str = "qfq",
    dates: list[str] | None = None,
) -> None:
    dates = dates or ["2025-01-02", "2025-01-03", "2025-01-06"]
    store = ParquetBarStore(bars_root)
    store.write_bars(
        pd.DataFrame(
            {
                "date": pd.to_datetime(dates),
                "symbol": [symbol, symbol, symbol],
                "open": [10.0, 10.5, 10.8],
                "high": [11.0, 11.2, 11.4],
                "low": [9.8, 10.1, 10.4],
                "close": [10.5, 10.8, 11.0],
                "volume": [1000, 1200, 1400],
                "amount": [10500.0, 12960.0, 15400.0],
                "frequency": [frequency, frequency, frequency],
                "adjust": [adjust, adjust, adjust],
            }
        )
    )


def test_build_kline_payload_reads_cached_bars_and_universe_metadata(tmp_path: Path):
    bars_root = tmp_path / "bars"
    _write_cached_bars(bars_root, "000001.SZ")
    _write_cached_bars(bars_root, "600000.SH")
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text(
        "symbol,code,name,exchange,board,list_date,industry\n"
        "000001.SZ,000001,平安银行,SZ,主板,1991-04-03,J 金融业\n"
        "600000.SH,600000,浦发银行,SH,主板,1999-11-10,\n",
        encoding="utf-8",
    )

    payload = build_kline_payload(bars_root, universe_path=universe_path, limit=2)

    assert payload["frequency"] == "1d"
    assert payload["adjust"] == "qfq"
    assert [item["symbol"] for item in payload["symbols"]] == ["000001.SZ", "600000.SH"]
    first = payload["symbols"][0]
    assert first["name"] == "平安银行"
    assert first["exchange"] == "SZ"
    assert first["board"] == "主板"
    assert [bar["date"] for bar in first["bars"]] == ["2025-01-03", "2025-01-06"]
    assert first["bars"][-1]["close"] == 11.0


def test_build_kline_payload_discovers_crypto_symbols_and_multiple_frequencies(
    tmp_path: Path,
):
    bars_root = tmp_path / "bars"
    _write_cached_bars(
        bars_root,
        "BTC/USDT",
        frequency="1d",
        adjust="none",
        dates=["2025-01-01", "2025-01-02", "2025-01-03"],
    )
    _write_cached_bars(
        bars_root,
        "BTC/USDT",
        frequency="4h",
        adjust="none",
        dates=["2025-01-02 00:00:00", "2025-01-02 04:00:00", "2025-01-02 08:00:00"],
    )

    payload = build_kline_payload(
        bars_root, symbols=["BTC/USDT"], limit=2, frequency=None, adjust="none"
    )

    item = payload["symbols"][0]
    assert item["symbol"] == "BTC/USDT"
    assert item["exchange"] == "Crypto"
    assert item["board"] == "Spot"
    assert [series["frequency"] for series in item["series"]] == ["4h", "1d"]
    assert item["series"][0]["first_bar"] == "2025-01-02T00:00:00"
    assert item["series"][0]["last_bar"] == "2025-01-02T08:00:00"
    assert item["series"][0]["bars"][-1]["date"] == "2025-01-02T08:00:00"
    assert item["series"][1]["rows"] == 3
    assert item["series"][1]["years"] == [2025]
    assert item["series"][1]["first_bar"] == "2025-01-01"
    assert item["series"][1]["last_bar"] == "2025-01-03"
    assert [bar["date"] for bar in item["series"][1]["bars"]] == [
        "2025-01-02",
        "2025-01-03",
    ]


def test_build_kline_payload_honors_frequency_filter_for_crypto_cache(
    tmp_path: Path,
):
    bars_root = tmp_path / "bars"
    _write_cached_bars(bars_root, "BTC/USDT", frequency="1d", adjust="none")
    _write_cached_bars(
        bars_root,
        "BTC/USDT",
        frequency="4h",
        adjust="none",
        dates=["2025-01-02 00:00:00", "2025-01-02 04:00:00", "2025-01-02 08:00:00"],
    )

    payload = build_kline_payload(
        bars_root, symbols=["BTC/USDT"], limit=2, frequency="4h", adjust="none"
    )

    assert [series["frequency"] for series in payload["symbols"][0]["series"]] == ["4h"]


def test_build_kline_payload_combines_year_partitions_into_one_series(tmp_path: Path):
    bars_root = tmp_path / "bars"
    _write_cached_bars(
        bars_root,
        "BTC/USDT",
        frequency="1d",
        adjust="none",
        dates=["2024-12-31", "2025-01-01", "2025-01-02"],
    )

    payload = build_kline_payload(
        bars_root, symbols=["BTC/USDT"], limit=10, frequency="1d", adjust="none"
    )

    series = payload["symbols"][0]["series"]
    assert len(series) == 1
    assert series[0]["frequency"] == "1d"
    assert series[0]["rows"] == 3
    assert series[0]["years"] == [2024, 2025]
    assert [bar["date"] for bar in series[0]["bars"]] == [
        "2024-12-31",
        "2025-01-01",
        "2025-01-02",
    ]


def test_build_kline_payload_limit_zero_embeds_all_cached_bars(tmp_path: Path):
    bars_root = tmp_path / "bars"
    _write_cached_bars(
        bars_root,
        "BTC/USDT",
        frequency="1d",
        adjust="none",
        dates=["2025-01-01", "2025-01-02", "2025-01-03"],
    )

    payload = build_kline_payload(
        bars_root, symbols=["BTC/USDT"], limit=0, frequency="1d", adjust="none"
    )

    series = payload["symbols"][0]["series"][0]
    assert series["rows"] == 3
    assert series["loaded_rows"] == 3
    assert [bar["date"] for bar in series["bars"]] == [
        "2025-01-01",
        "2025-01-02",
        "2025-01-03",
    ]


def test_write_kline_viewer_embeds_payload_for_file_url_usage(tmp_path: Path):
    payload = {
        "frequency": "1d",
        "adjust": "qfq",
        "symbols": [
            {
                "symbol": "000001.SZ",
                "name": "平安银行",
                "exchange": "SZ",
                "board": "主板",
                "series": [
                    {
                        "frequency": "1d",
                        "adjust": "qfq",
                        "rows": 1,
                        "loaded_rows": 1,
                        "first_bar": "2025-01-02",
                        "last_bar": "2025-01-02",
                        "years": [2025],
                        "bars": [
                            {
                                "date": "2025-01-02",
                                "open": 10.0,
                                "high": 11.0,
                                "low": 9.8,
                                "close": 10.5,
                                "volume": 1000,
                                "amount": 10500.0,
                            }
                        ],
                    }
                ],
                "bars": [
                    {
                        "date": "2025-01-02",
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.8,
                        "close": 10.5,
                        "volume": 1000,
                        "amount": 10500.0,
                    }
                ],
            }
        ],
    }
    output_path = tmp_path / "kline_viewer.html"

    write_kline_viewer(payload, output_path)

    html = output_path.read_text(encoding="utf-8")
    assert "kline-payload" in html
    assert "000001.SZ" in html
    assert "Plotly.newPlot" in html
    assert 'type: "category"' in html
    assert "title: {" not in html
    assert 'yanchor: "bottom"' in html
    assert 'tickformat: ".2f"' in html
    assert "frequencyButtons" in html
    assert "dataStatusDrawer" in html
    assert "toggleDataStatus" in html
    assert "seriesByFrequency" in html
    assert "windowSizeSelect" in html
    assert "windowSlider" in html
    assert "updateWindowControls" in html
    assert "flex-wrap: wrap" in html
    assert 'class="topbar-header"' in html
    assert 'class="status-action" id="dataStatusButton"' in html
    assert 'id="dataStatusButtonMeta"' in html
    assert html.index('id="dataStatusButton"') < html.index('class="controls"')
    assert "dataStatusButtonMeta.textContent" in html
    assert 'class="control control-position"' in html
    assert "windowMeta.title" in html
    assert "${state.windowStart + 1}-${end} / ${compact(loaded)}" in html
    assert "loaded_rows" in html
    assert "status-symbol-group" in html
    assert "rangeButtons" not in html
    assert "60D" not in html
    assert '|| "Unknown"' in html
