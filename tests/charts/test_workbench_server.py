from backtest.charts import workbench_server
from backtest.charts.workbench_server import build_kline_shell_payload, render_workbench_index_html


def test_render_workbench_index_html_links_both_chart_apps():
    html = render_workbench_index_html()

    assert "Backtest Workbench" in html
    assert 'href="/strategy-results"' in html
    assert "Strategy Results" in html
    assert 'href="/kline"' in html
    assert "K-line Viewer" in html


def test_render_workbench_index_html_hosts_data_source_monitor():
    html = render_workbench_index_html(
        data_api_base_url="http://127.0.0.1:8768/",
        data_api_token="monitor-token",
    )

    assert "workbench-index-payload" in html
    assert '"data_api_base_url":"http://127.0.0.1:8768"' in html
    assert '"data_api_token":"monitor-token"' in html
    assert 'id="dataSourceMonitor"' in html
    assert 'id="dataSourceDrawer"' in html
    assert 'id="dataSourceTabs"' in html
    assert 'id="taskSymbolSearch"' in html
    assert 'id="taskFrequencyFilters"' in html
    assert 'id="taskStatusFilters"' in html
    assert 'id="taskPreviousPageButton"' in html
    assert 'id="taskNextPageButton"' in html
    assert 'id="taskPageSizeSelect"' in html
    assert 'id="dataScheduleSummary"' in html
    assert 'id="dataScheduleRows"' in html
    assert 'id="dataScheduleRunRows"' in html
    assert "Schedule controls and crawl task monitor" in html
    assert "Schedule" in html
    assert "Recent Runs" in html
    assert "Trigger" in html
    assert "Repeat" in html
    assert "Next Run" in html
    assert "Last Job" in html
    assert "Triggered" in html
    assert "function dataApiUrl(path)" in html
    assert "function dataApiRequestOptions()" in html
    assert '"Authorization", `Bearer ${payload.data_api_token}`' in html
    assert 'fetch(dataApiUrl("/api/data-sources"), dataApiRequestOptions())' in html
    assert 'fetch(dataApiUrl(`/api/data/tasks/summary?source_id=${encodeURIComponent(source.source_id)}`), dataApiRequestOptions())' in html
    assert 'fetch(taskPageUrl(source.source_id, filters), dataApiRequestOptions())' in html
    assert 'fetch(dataApiUrl("/api/data/jobs"), dataApiRequestOptions())' in html
    assert 'fetch(dataApiUrl("/api/data/schedules"), dataApiRequestOptions())' in html
    assert 'fetch(dataApiUrl(`/api/data/schedules/${encodeURIComponent(schedule.schedule_id)}/runs`), dataApiRequestOptions())' in html
    assert "function renderScheduleRows()" in html
    assert "function renderScheduleRunRows()" in html
    assert "DATA_MONITOR_REFRESH_MS = 10000" in html
    assert 'document.addEventListener("visibilitychange", refreshDataMonitorWhenVisible)' in html
    assert "Submit" not in html
    assert "Retry" not in html
    assert "Cancel" not in html


def test_render_workbench_index_html_supports_schedule_controls():
    html = render_workbench_index_html(
        data_api_base_url="http://127.0.0.1:8768/",
        data_api_token="monitor-token",
    )

    assert "Actions" in html
    assert 'data-schedule-action="toggle"' in html
    assert 'data-schedule-action="run"' in html
    assert 'data-schedule-action="edit"' in html
    assert 'id="scheduleEditDialog"' in html
    assert 'id="scheduleEditForm"' in html
    assert 'id="scheduleEditName"' in html
    assert 'id="scheduleEditTriggerType"' in html
    assert 'id="scheduleEditRepeatMode"' in html
    assert 'id="scheduleEditSymbols"' in html
    assert 'id="scheduleEditDateRangeType"' in html
    assert 'id="scheduleEditRefreshExisting"' in html
    assert "function toggleSchedule(scheduleId)" in html
    assert "function openScheduleEditor(scheduleId)" in html
    assert "function saveScheduleEdits(event)" in html
    assert 'fetch(dataApiUrl(`/api/data/schedules/${encodeURIComponent(schedule.schedule_id)}/${schedule.enabled ? "disable" : "enable"}`), dataApiMutationOptions("POST"))' in html
    assert 'fetch(dataApiUrl(`/api/data/schedules/${encodeURIComponent(schedule.schedule_id)}/run-now`), dataApiMutationOptions("POST"))' in html
    assert 'fetch(dataApiUrl(`/api/data/schedules/${encodeURIComponent(schedule.schedule_id)}`), dataApiMutationOptions("PATCH", payload))' in html


def test_build_kline_shell_payload_includes_remote_data_api_base_url():
    payload = build_kline_shell_payload(
        default_window_size=5000,
        data_api_base_url="http://data-host:8768/",
        data_api_token="viewer-token",
    )

    assert payload == {
        "mode": "dynamic",
        "default_window_size": 5000,
        "links": {"workbench_home": "/"},
        "data_api_base_url": "http://data-host:8768",
        "data_api_token": "viewer-token",
    }


def test_workbench_home_receives_remote_data_api_base_url(monkeypatch):
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

    def fake_render_workbench_index_html(*, data_api_base_url=None, data_api_token=None):
        captured["home_data_api_base_url"] = data_api_base_url
        captured["home_data_api_token"] = data_api_token
        return "home shell"

    monkeypatch.setattr(workbench_server, "KlineCacheService", FakeKlineService)
    monkeypatch.setattr(workbench_server, "StrategyResultsService", FakeStrategyService)
    monkeypatch.setattr(workbench_server, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(workbench_server, "render_workbench_index_html", fake_render_workbench_index_html)
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
        data_api_token="viewer-token",
    )

    assert captured["home_data_api_base_url"] == "http://data-host:8768"
    assert captured["home_data_api_token"] == "viewer-token"
    assert captured["strategy_payload"] == {
        "mode": "dynamic",
        "title": "Strategy Results",
        "links": {"workbench_home": "/"},
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
