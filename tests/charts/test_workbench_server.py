from backtest.charts import workbench_server
from backtest.charts.workbench_server import build_kline_shell_payload, render_workbench_index_html


def test_render_workbench_index_html_links_both_chart_apps():
    html = render_workbench_index_html()

    assert "Backtest Workbench" in html
    assert 'href="/strategy-results"' in html
    assert "Strategy Results" in html
    assert 'href="/kline"' in html
    assert "K-line Viewer" in html


def test_build_kline_shell_payload_includes_remote_data_api_base_url():
    payload = build_kline_shell_payload(
        default_window_size=5000,
        data_api_base_url="http://data-host:8768/",
    )

    assert payload == {
        "mode": "dynamic",
        "default_window_size": 5000,
        "links": {"workbench_home": "/"},
        "data_api_base_url": "http://data-host:8768",
    }


def test_workbench_strategy_shell_includes_remote_data_api_base_url(monkeypatch):
    captured = {}

    class FakeKlineService:
        def __init__(self, **kwargs):
            pass

    class FakeStrategyService:
        def __init__(self, **kwargs):
            pass

    class FakeServer:
        def __init__(self, address, handler_class):
            pass

        def serve_forever(self):
            return None

        def server_close(self):
            return None

    def fake_render_strategy_results_catalog_html(payload):
        captured["strategy_payload"] = payload
        return "strategy shell"

    monkeypatch.setattr(workbench_server, "KlineCacheService", FakeKlineService)
    monkeypatch.setattr(workbench_server, "StrategyResultsService", FakeStrategyService)
    monkeypatch.setattr(workbench_server, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(
        workbench_server,
        "render_strategy_results_catalog_html",
        fake_render_strategy_results_catalog_html,
    )

    workbench_server.serve_chart_workbench(
        kline_sources=[],
        results_roots=[],
        bars_root=".",
        data_api_base_url="http://data-host:8768/",
    )

    assert captured["strategy_payload"] == {
        "mode": "dynamic",
        "title": "Strategy Results",
        "links": {"workbench_home": "/"},
        "data_api_base_url": "http://data-host:8768",
    }


def test_workbench_server_supports_legacy_and_kline_api_manifest_routes(monkeypatch):
    captured = {}

    class FakeKlineService:
        def __init__(self, **kwargs):
            pass

        def manifest(self, *, default_window_size):
            return {"window": default_window_size}

        def bars(self, **kwargs):
            return {"source_id": kwargs["source_id"], "symbol": kwargs["symbol"]}

    class FakeStrategyService:
        def __init__(self, **kwargs):
            pass

    class FakeServer:
        def __init__(self, address, handler_class):
            captured["handler_class"] = handler_class

        def serve_forever(self):
            return None

        def server_close(self):
            return None

    monkeypatch.setattr(workbench_server, "KlineCacheService", FakeKlineService)
    monkeypatch.setattr(workbench_server, "StrategyResultsService", FakeStrategyService)
    monkeypatch.setattr(workbench_server, "ThreadingHTTPServer", FakeServer)

    workbench_server.serve_chart_workbench(
        kline_sources=[],
        results_roots=[],
        bars_root=".",
        default_window_size=321,
    )
    handler_class = captured["handler_class"]

    for path in ["/api/manifest", "/api/kline/manifest"]:
        sent = {}
        handler = object.__new__(handler_class)
        handler.path = path
        handler._send_json = lambda payload, status=None: sent.update(payload=payload)

        handler.do_GET()

        assert sent["payload"] == {"window": 321}

    for path in [
        "/api/bars?source_id=bitget&symbol=BTC%2FUSDT&frequency=1d",
        "/api/kline/bars?source_id=bitget&symbol=BTC%2FUSDT&frequency=1d",
    ]:
        sent = {}
        handler = object.__new__(handler_class)
        handler.path = path
        handler._send_json = lambda payload, status=None: sent.update(payload=payload)

        handler.do_GET()

        assert sent["payload"] == {"source_id": "bitget", "symbol": "BTC/USDT"}
