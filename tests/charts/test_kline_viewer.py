from pathlib import Path

import pandas as pd

from backtest.charts.kline_viewer import build_kline_payload, render_kline_viewer_html, write_kline_viewer
from backtest.charts import kline_server
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


def test_build_kline_payload_groups_multiple_source_roots(tmp_path: Path):
    bitget_root = tmp_path / "bitget" / "bars"
    binance_root = tmp_path / "binance" / "bars"
    _write_cached_bars(
        bitget_root,
        "BTC/USDT",
        frequency="1m",
        adjust="none",
        dates=["2025-01-01 00:00:00", "2025-01-01 00:01:00", "2025-01-01 00:02:00"],
    )
    _write_cached_bars(
        binance_root,
        "BTC/USDT",
        frequency="1m",
        adjust="none",
        dates=["2025-01-01 00:00:00", "2025-01-01 00:01:00", "2025-01-01 00:02:00"],
    )
    _write_cached_bars(
        binance_root,
        "ETH/USDT",
        frequency="1d",
        adjust="none",
        dates=["2025-01-01", "2025-01-02", "2025-01-03"],
    )

    payload = build_kline_payload(
        bitget_root,
        source_roots=[("bitget", bitget_root), ("binance", binance_root)],
        frequency=None,
        adjust="none",
        limit=2,
    )

    assert [source["source_id"] for source in payload["sources"]] == ["bitget", "binance"]
    assert payload["sources"][0]["source_label"] == "Bitget"
    assert [item["symbol"] for item in payload["sources"][0]["symbols"]] == ["BTC/USDT"]
    assert [item["symbol"] for item in payload["sources"][1]["symbols"]] == [
        "BTC/USDT",
        "ETH/USDT",
    ]
    assert payload["symbols"] == payload["sources"][0]["symbols"]
    assert payload["source_id"] == "bitget"
    assert payload["source_label"] == "Bitget"


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
    assert "width: max-content" in html
    assert "windowSizeSelect" in html
    assert "windowOverlapSelect" in html
    assert "availableWindowRows" in html
    assert "dynamicMode ? Number(series?.rows || embedded || 0) : embedded" in html
    assert "pageStepSize" in html
    assert "windowSlider" in html
    assert "updateWindowControls" in html
    assert "flex-wrap: wrap" in html
    assert 'class="topbar-header"' in html
    assert 'class="data-status-button" id="dataStatusButton"' in html
    assert 'id="dataStatusStripMeta"' in html
    assert html.index('id="dataStatusButton"') < html.index('class="controls"')
    assert "dataStatusStripMeta.textContent" in html
    assert 'class="time-window" id="timeWindowBar"' in html
    assert 'class="position-meta" id="windowMeta"' in html
    assert 'class="position-control"' in html
    assert 'id="windowRowsMeta"' in html
    assert 'id="windowTimeMeta"' in html
    assert 'id="olderPageButton"' in html
    assert 'id="windowOverlapSelect"' in html
    assert "Overlap" in html
    assert '<option value="0.8" selected>80%</option>' in html
    assert "default_window_overlap ?? 0.8" in html
    assert "windowMeta.title" in html
    assert "windowRowsMeta.textContent" in html
    assert 'const KLINE_DISPLAY_TIME_ZONE = "Asia/Shanghai";' in html
    assert "function formatBarDateTime(value, frequency)" in html
    assert "function jumpInputToApiValue(value, daily)" in html
    assert "bars.map((bar) => formatBarDateTime(bar.date, series?.frequency || state.frequency))" in html
    assert "loaded_rows" in html
    assert "status-symbol-group" in html
    assert 'id="dataStatusPager"' in html
    assert "DATA_STATUS_PAGE_SIZE = 50" in html
    assert "symbols.slice(start, start + DATA_STATUS_PAGE_SIZE)" in html
    assert "sourceButtons" in html
    assert "currentSource" in html
    assert "Source" in html
    assert "rangeButtons" not in html
    assert "60D" not in html
    assert '|| "Unclassified"' in html


def test_write_kline_viewer_supports_dynamic_api_mode(tmp_path: Path):
    output_path = tmp_path / "dynamic_viewer.html"

    write_kline_viewer(
        {"mode": "dynamic", "default_window_size": 5000, "adjust": "none"},
        output_path,
    )

    html = output_path.read_text(encoding="utf-8")
    assert 'mode": "dynamic"' not in html
    assert '"mode":"dynamic"' in html
    assert "loadManifest" in html
    assert '"/api/kline/manifest?symbols=0"' in html
    assert "loadSymbolsPage" in html
    assert "loadRemoteDataSources" in html
    assert 'requestJson("/api/data-sources", "Data sources")' in html
    assert "loadTaskSymbolsPage" in html
    assert "requestJson(`/api/data/tasks?${params.toString()}`, \"Task symbols\")" in html
    assert "useManifestSymbolPage" in html
    assert "loadLegacySymbolsPage" in html
    assert "source.all_symbols" in html
    assert "legacy: true" in html
    assert "await useManifestSymbolPage({ loadBars: true })" in html
    assert 'requestJson(`/api/kline/symbols?${params.toString()}`, "Symbol")' in html
    assert "apiUrl(`/api/kline/bars?${params.toString()}`)" in html
    assert "olderPageButton" in html
    assert "newerPageButton" in html
    assert "latestPageButton" in html
    assert "jumpTimeInput" in html
    assert 'type="datetime-local"' in html
    assert "configureJumpControl" in html
    assert "frequencyStepSeconds" in html
    assert "toJumpInputValue" in html
    assert "DYNAMIC_BUFFER_MULTIPLIER" in html
    assert "bufferedWindowSize" in html
    assert "globalWindowOffset" in html
    assert "targetWindowOffset" in html
    assert "targetBufferOffset" in html
    assert "windowOverlapRatio" in html
    assert "pageStepSize" in html
    assert "current - step" in html
    assert "current + step" in html
    assert "canRenderGlobalOffset" in html
    assert "renderGlobalOffset" in html
    assert "navigateToGlobalOffset" in html
    assert "windowSlider.max = String(globalMaxStart)" in html
    assert "Loaded" not in html


def test_render_kline_viewer_honors_dynamic_default_selection():
    html = render_kline_viewer_html(
        {
            "mode": "dynamic",
            "default_source_id": "a_share",
            "default_symbol": "000001.SZ",
            "default_frequency": "1d",
        }
    )

    assert '"default_source_id":"a_share"' in html
    assert '"default_symbol":"000001.SZ"' in html
    assert '"default_frequency":"1d"' in html
    assert 'sourceId: payload.default_source_id || sources[0]?.source_id || "default"' in html
    assert 'symbol: payload.default_symbol || sources[0]?.symbols?.[0]?.symbol || ""' in html
    assert 'frequency: payload.default_frequency || sources[0]?.symbols?.[0]?.series?.[0]?.frequency || payload.frequency || "1d"' in html
    assert "const requestedSymbol = payload.default_symbol || state.symbol;" in html
    assert "const requestedFrequency = payload.default_frequency || state.frequency;" in html


def test_render_kline_viewer_supports_remote_data_api_base_url():
    html = render_kline_viewer_html(
        {
            "mode": "dynamic",
            "default_window_size": 5000,
            "data_api_base_url": "http://data-host:8768",
            "data_api_token": "viewer-token",
        }
    )

    assert '"data_api_base_url":"http://data-host:8768"' in html
    assert '"data_api_token":"viewer-token"' in html
    assert "function apiUrl(path)" in html
    assert "function apiRequestOptions()" in html
    assert '"Authorization", `Bearer ${payload.data_api_token}`' in html
    assert "function requestJson(path, label)" in html
    assert "const manifest = await requestJson(manifestPath, \"Manifest\")" in html
    assert "requestJson(`/api/kline/symbols?${params.toString()}`, \"Symbol\")" in html
    assert "requestJson(`/api/data/tasks?${params.toString()}`, \"Task symbols\")" in html
    assert "fetch(apiUrl(`/api/kline/bars?${params.toString()}`), apiRequestOptions())" in html


def test_render_kline_viewer_supports_workbench_home_link():
    html = render_kline_viewer_html({"mode": "dynamic", "links": {"workbench_home": "/"}})

    assert 'id="workbenchHomeLink"' in html
    assert "Workbench Home" in html
    assert "workbenchHomeHref" in html
    assert 'class="header-actions"' in html
    assert 'class="home-link" id="workbenchHomeLink"' in html
    assert 'class="data-status-button" id="dataStatusButton"' in html
    assert 'id="dataStatusStripMeta"' in html
    assert 'id="dataStatusPager"' in html
    assert 'id="frequencyButtons" aria-label="Frequency"></div>' in html
    assert 'class="toolbar-button data-status-control" id="dataStatusButton"' not in html
    assert 'class="status-action"' not in html
    assert 'id="dataStatusButtonMeta"' not in html


def test_kline_server_supports_legacy_and_kline_api_manifest_routes(monkeypatch):
    captured = {}

    class FakeService:
        def __init__(self, **kwargs):
            pass

        def manifest(self, *, default_window_size, include_symbols=True):
            return {"window": default_window_size, "include_symbols": include_symbols}

        def symbols(self, **kwargs):
            return {"limit": kwargs["limit"], "source_id": kwargs["source_id"]}

        def bars(self, **kwargs):
            return {"symbol": kwargs["symbol"], "frequency": kwargs["frequency"]}

    class FakeServer:
        def __init__(self, address, handler_class):
            captured["handler_class"] = handler_class

        def serve_forever(self):
            return None

        def server_close(self):
            return None

    monkeypatch.setattr(kline_server, "KlineCacheService", FakeService)
    monkeypatch.setattr(kline_server, "ThreadingHTTPServer", FakeServer)

    kline_server.serve_kline_viewer(default_window_size=123)
    handler_class = captured["handler_class"]

    for path in ["/api/manifest", "/api/kline/manifest"]:
        sent = {}
        handler = object.__new__(handler_class)
        handler.path = path
        handler._send_json = lambda payload, status=None: sent.update(payload=payload)

        handler.do_GET()

        assert sent["payload"] == {"window": 123, "include_symbols": True}

    sent = {}
    handler = object.__new__(handler_class)
    handler.path = "/api/kline/manifest?symbols=0"
    handler._send_json = lambda payload, status=None: sent.update(payload=payload)

    handler.do_GET()

    assert sent["payload"] == {"window": 123, "include_symbols": False}

    sent = {}
    handler = object.__new__(handler_class)
    handler.path = "/api/kline/symbols?source_id=bitget&limit=25"
    handler._send_json = lambda payload, status=None: sent.update(payload=payload)

    handler.do_GET()

    assert sent["payload"] == {"limit": 25, "source_id": "bitget"}

    for path in [
        "/api/bars?symbol=BTC%2FUSDT&frequency=1d",
        "/api/kline/bars?symbol=BTC%2FUSDT&frequency=1d",
    ]:
        sent = {}
        handler = object.__new__(handler_class)
        handler.path = path
        handler._send_json = lambda payload, status=None: sent.update(payload=payload)

        handler.do_GET()

        assert sent["payload"] == {"symbol": "BTC/USDT", "frequency": "1d"}
