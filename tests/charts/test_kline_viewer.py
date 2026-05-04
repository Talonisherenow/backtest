from pathlib import Path

import pandas as pd

from backtest.charts.kline_viewer import build_kline_payload, write_kline_viewer
from backtest.data.store import ParquetBarStore


def _write_cached_bars(bars_root: Path, symbol: str) -> None:
    store = ParquetBarStore(bars_root)
    store.write_bars(
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
                "symbol": [symbol, symbol, symbol],
                "open": [10.0, 10.5, 10.8],
                "high": [11.0, 11.2, 11.4],
                "low": [9.8, 10.1, 10.4],
                "close": [10.5, 10.8, 11.0],
                "volume": [1000, 1200, 1400],
                "amount": [10500.0, 12960.0, 15400.0],
                "frequency": ["1d", "1d", "1d"],
                "adjust": ["qfq", "qfq", "qfq"],
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
