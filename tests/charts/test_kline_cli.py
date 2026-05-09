from pathlib import Path

from typer.testing import CliRunner

from backtest.cli import chart as chart_cli
from backtest.cli.app import app


def test_chart_serve_cli_passes_dynamic_server_options(tmp_path: Path, monkeypatch):
    bars_root = tmp_path / "bars"
    bars_root.mkdir()
    universe_path = tmp_path / "universe.csv"
    universe_path.write_text("symbol,code,name\nBTC/USDT,BTC/USDT,Bitcoin\n", encoding="utf-8")
    captured = {}

    def fake_serve_kline_viewer(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(chart_cli, "serve_kline_viewer", fake_serve_kline_viewer)

    result = CliRunner().invoke(
        app,
        [
            "chart",
            "serve",
            "--bars-root",
            str(bars_root),
            "--universe",
            str(universe_path),
            "--host",
            "127.0.0.1",
            "--port",
            "9876",
            "--window-size",
            "5000",
            "--adjust",
            "none",
        ],
    )

    assert result.exit_code == 0
    assert captured["bars_root"] == bars_root
    assert captured["universe_path"] == universe_path
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 9876
    assert captured["default_window_size"] == 5000
    assert captured["adjust"] == "none"


def test_chart_serve_cli_auto_discovers_source_roots_from_parent_root(
    tmp_path: Path, monkeypatch
):
    crypto_root = tmp_path / "crypto"
    bitget_root = crypto_root / "bitget" / "bars"
    binance_root = crypto_root / "binance" / "bars"
    (bitget_root / "frequency=1d" / "adjust=none").mkdir(parents=True)
    (binance_root / "frequency=1d" / "adjust=none").mkdir(parents=True)
    captured = {}

    def fake_serve_kline_viewer(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(chart_cli, "serve_kline_viewer", fake_serve_kline_viewer)

    result = CliRunner().invoke(
        app,
        [
            "chart",
            "serve",
            "--bars-root",
            str(crypto_root),
            "--adjust",
            "none",
        ],
    )

    assert result.exit_code == 0
    assert captured["bars_root"] == crypto_root
    assert captured["source_roots"] == [
        ("binance", binance_root),
        ("bitget", bitget_root),
    ]


def test_chart_viewer_cli_auto_discovers_source_roots_from_parent_root(
    tmp_path: Path, monkeypatch
):
    crypto_root = tmp_path / "crypto"
    bitget_root = crypto_root / "bitget" / "bars"
    okx_root = crypto_root / "okx" / "bars"
    (bitget_root / "frequency=1m" / "adjust=none").mkdir(parents=True)
    (okx_root / "frequency=1m" / "adjust=none").mkdir(parents=True)
    output_path = tmp_path / "viewer.html"
    captured = {}

    def fake_build_kline_payload(**kwargs):
        captured.update(kwargs)
        return {"symbols": [{"symbol": "BTC/USDT"}]}

    def fake_write_kline_viewer(payload, path):
        captured["output_path"] = path
        path.write_text("viewer", encoding="utf-8")

    monkeypatch.setattr(chart_cli, "build_kline_payload", fake_build_kline_payload)
    monkeypatch.setattr(chart_cli, "write_kline_viewer", fake_write_kline_viewer)

    result = CliRunner().invoke(
        app,
        [
            "chart",
            "viewer",
            "--bars-root",
            str(crypto_root),
            "--output",
            str(output_path),
            "--adjust",
            "none",
        ],
    )

    assert result.exit_code == 0
    assert captured["source_roots"] == [
        ("bitget", bitget_root),
        ("okx", okx_root),
    ]
