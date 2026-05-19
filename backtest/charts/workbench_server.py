from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from backtest.charts.kline_service import KlineCacheService, KlineSource
from backtest.charts.kline_viewer import render_kline_viewer_html
from backtest.charts.strategy_account_viewer import render_strategy_account_viewer_html
from backtest.charts.strategy_order_drilldown_viewer import render_strategy_order_drilldown_viewer_html
from backtest.charts.strategy_results_catalog import render_strategy_results_catalog_html
from backtest.charts.strategy_results_service import StrategyResultsService


def serve_chart_workbench(
    *,
    kline_sources: list[KlineSource],
    results_roots: list[Path],
    bars_root: Path,
    host: str = "127.0.0.1",
    port: int = 8767,
    default_window_size: int = 300,
    data_api_base_url: str | None = None,
    data_api_token: str | None = None,
) -> None:
    kline_service = KlineCacheService(sources=kline_sources)
    strategy_service = StrategyResultsService(results_roots=results_roots, bars_root=bars_root)
    normalized_data_api_base_url = data_api_base_url.rstrip("/") if data_api_base_url else None
    normalized_data_api_token = data_api_token.strip() if data_api_token else None
    index_html = render_workbench_index_html(
        data_api_base_url=normalized_data_api_base_url,
        data_api_token=normalized_data_api_token,
    ).encode("utf-8")
    kline_html = render_kline_viewer_html(
        build_kline_shell_payload(
            default_window_size=default_window_size,
            data_api_base_url=normalized_data_api_base_url,
            data_api_token=normalized_data_api_token,
        )
    ).encode("utf-8")
    strategy_payload = {"mode": "dynamic", "title": "Strategy Results", "links": {"workbench_home": "/"}}
    strategy_html = render_strategy_results_catalog_html(strategy_payload).encode("utf-8")

    class WorkbenchHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            if parsed.path == "/":
                self._send_bytes(index_html, "text/html; charset=utf-8")
                return
            if parsed.path in {"/kline", "/kline_viewer.html", "/crypto_kline_viewer.html"}:
                self._send_bytes(kline_html, "text/html; charset=utf-8")
                return
            if parsed.path in {"/api/manifest", "/api/kline/manifest"}:
                self._send_json(kline_service.manifest(default_window_size=default_window_size))
                return
            if parsed.path in {"/api/bars", "/api/kline/bars"}:
                self._handle_kline_bars(params)
                return
            if parsed.path == "/strategy-results":
                self._send_bytes(strategy_html, "text/html; charset=utf-8")
                return
            if parsed.path == "/api/strategy-results":
                self._send_json(strategy_service.catalog())
                return
            if parsed.path == "/api/strategy-results/account":
                self._handle_strategy_account_json(params)
                return
            if parsed.path == "/api/strategy-results/drilldown":
                self._handle_strategy_drilldown_json(params)
                return
            if parsed.path == "/strategy-results/account":
                self._handle_strategy_account_html(params)
                return
            if parsed.path == "/strategy-results/drilldown":
                self._handle_strategy_drilldown_html(params)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

        def log_message(self, format: str, *args: object) -> None:
            return

        def _handle_kline_bars(self, params: dict[str, list[str]]) -> None:
            try:
                result = kline_service.bars(
                    source_id=self._required(params, "source_id"),
                    symbol=unquote(self._required(params, "symbol")),
                    frequency=self._required(params, "frequency"),
                    adjust=self._optional(params, "adjust"),
                    limit=self._int_param(params, "limit", 300),
                    offset=self._optional_int(params, "offset"),
                    start=self._optional(params, "start"),
                    anchor=self._optional(params, "anchor", "latest") or "latest",
                )
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)

        def _handle_strategy_account_json(self, params: dict[str, list[str]]) -> None:
            try:
                self._send_json(strategy_service.account_payload(self._required(params, "case_id")))
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def _handle_strategy_drilldown_json(self, params: dict[str, list[str]]) -> None:
            try:
                self._send_json(
                    strategy_service.drilldown_payload(
                        self._required(params, "case_id"),
                        default_symbol=self._optional(params, "symbol"),
                    )
                )
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def _handle_strategy_account_html(self, params: dict[str, list[str]]) -> None:
            try:
                body = render_strategy_account_viewer_html(
                    strategy_service.account_payload(self._required(params, "case_id"))
                ).encode("utf-8")
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_bytes(body, "text/html; charset=utf-8")

        def _handle_strategy_drilldown_html(self, params: dict[str, list[str]]) -> None:
            try:
                body = render_strategy_order_drilldown_viewer_html(
                    strategy_service.drilldown_payload(
                        self._required(params, "case_id"),
                        default_symbol=self._optional(params, "symbol"),
                    )
                ).encode("utf-8")
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_bytes(body, "text/html; charset=utf-8")

        def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._send_bytes(body, "application/json; charset=utf-8", status=status)

        def _send_bytes(
            self,
            body: bytes,
            content_type: str,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        @staticmethod
        def _required(params: dict[str, list[str]], name: str) -> str:
            value = WorkbenchHandler._optional(params, name)
            if value is None:
                raise ValueError(f"Missing required parameter: {name}")
            return value

        @staticmethod
        def _optional(params: dict[str, list[str]], name: str, default: str | None = None) -> str | None:
            values = params.get(name)
            if not values:
                return default
            return values[0]

        @staticmethod
        def _int_param(params: dict[str, list[str]], name: str, default: int) -> int:
            value = WorkbenchHandler._optional(params, name)
            if value is None:
                return default
            return int(value)

        @staticmethod
        def _optional_int(params: dict[str, list[str]], name: str) -> int | None:
            value = WorkbenchHandler._optional(params, name)
            if value is None:
                return None
            return int(value)

    server = ThreadingHTTPServer((host, port), WorkbenchHandler)
    print(f"Serving chart workbench at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def build_kline_shell_payload(
    default_window_size: int,
    data_api_base_url: str | None = None,
    data_api_token: str | None = None,
) -> dict:
    payload = {
        "mode": "dynamic",
        "default_window_size": default_window_size,
        "links": {"workbench_home": "/"},
    }
    if data_api_base_url:
        payload["data_api_base_url"] = data_api_base_url.rstrip("/")
    if data_api_token:
        payload["data_api_token"] = data_api_token.strip()
    return payload


def render_workbench_index_html(
    data_api_base_url: str | None = None,
    data_api_token: str | None = None,
) -> str:
    payload = {}
    if data_api_base_url:
        payload["data_api_base_url"] = data_api_base_url.rstrip("/")
    if data_api_token:
        payload["data_api_token"] = data_api_token.strip()
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    safe_payload = payload_json.replace("</", "<\\/")
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Backtest Workbench</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f7fb;
      --surface: #ffffff;
      --line: #d8e0e8;
      --line-soft: #edf1f5;
      --text: #1d2733;
      --muted: #667789;
      --blue: #1d5fd1;
      --green: #168a5a;
      --red: #c2412d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    }
    header {
      padding: 18px 22px;
      background: var(--surface);
      border-bottom: 1px solid var(--line);
    }
    h1 { margin: 0; font-size: 22px; }
    .subtitle { margin-top: 6px; color: var(--muted); font-size: 13px; }
    .data-monitor {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      margin: 18px 22px 0;
      padding: 10px 12px;
      background: #f8fbff;
      border: 1px solid #d7e3ef;
      border-radius: 8px;
    }
    .data-monitor[hidden] { display: none; }
    .data-monitor-title {
      font-weight: 800;
      font-size: 13px;
      white-space: nowrap;
    }
    .data-monitor-body {
      display: grid;
      gap: 8px;
      min-width: 0;
    }
    .data-source-summary {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      min-width: 0;
    }
    .data-source-pill {
      display: inline-flex;
      gap: 6px;
      align-items: center;
      min-height: 28px;
      padding: 0 9px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    .data-source-pill strong { color: var(--text); }
    .data-source-pill.failed { border-color: #f1b8ad; background: #fff7f5; }
    .data-source-pill.active { border-color: #b7d4ff; background: #f4f8ff; }
    .data-monitor-meta {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .monitor-actions {
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: flex-end;
    }
    .text-button {
      min-height: 30px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--blue);
      font: inherit;
      font-size: 12px;
      font-weight: 800;
      cursor: pointer;
      white-space: nowrap;
    }
    .text-button:hover { background: #f8fafc; border-color: #b8c7d6; }
    .drawer-backdrop {
      position: fixed;
      inset: 0;
      z-index: 19;
      background: rgb(21 31 43 / 24%);
    }
    .drawer-backdrop[hidden] { display: none; }
    .data-drawer {
      position: fixed;
      top: 0;
      right: 0;
      z-index: 20;
      width: min(720px, 94vw);
      height: 100vh;
      display: grid;
      grid-template-rows: auto auto auto auto auto auto minmax(0, 1fr) auto;
      background: var(--surface);
      border-left: 1px solid var(--line);
      box-shadow: -18px 0 40px rgb(21 31 43 / 18%);
    }
    .data-drawer[hidden] { display: none; }
    .drawer-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 16px;
      border-bottom: 1px solid var(--line);
    }
    .drawer-header h2 { margin: 0; font-size: 16px; }
    .drawer-meta {
      padding: 10px 16px;
      color: var(--muted);
      font-size: 12px;
      border-bottom: 1px solid var(--line);
    }
    .source-tabs {
      display: flex;
      gap: 6px;
      overflow-x: auto;
      padding: 10px 16px;
      border-bottom: 1px solid var(--line);
    }
    .source-tab {
      min-height: 30px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--muted);
      font: inherit;
      font-size: 12px;
      font-weight: 800;
      cursor: pointer;
      white-space: nowrap;
    }
    .source-tab.active {
      border-color: #b7d4ff;
      background: #eef5ff;
      color: #195bb8;
    }
    .drawer-filters {
      display: grid;
      grid-template-columns: minmax(140px, 1fr) minmax(0, 1.2fr) minmax(0, 1.2fr) auto;
      gap: 10px;
      align-items: start;
      padding: 12px 16px;
      border-bottom: 1px solid var(--line);
    }
    .filter-field,
    .filter-group {
      display: grid;
      gap: 6px;
      min-width: 0;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
    }
    .filter-field input,
    .filter-field select {
      min-height: 32px;
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 9px;
      background: #fff;
      color: var(--text);
      font: inherit;
      font-size: 12px;
      text-transform: none;
    }
    .checkbox-pills {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      min-height: 32px;
      align-content: start;
    }
    .checkbox-pill {
      display: inline-flex;
      gap: 5px;
      align-items: center;
      min-height: 28px;
      padding: 0 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff;
      color: var(--text);
      font-size: 12px;
      font-weight: 700;
      text-transform: none;
      white-space: nowrap;
    }
    .checkbox-pill input { margin: 0; }
    .schedule-panel {
      display: grid;
      gap: 8px;
      max-height: 220px;
      overflow: auto;
      padding: 10px 16px 12px;
      border-bottom: 1px solid var(--line);
    }
    .schedule-runs-panel { max-height: 180px; }
    .schedule-actions {
      display: flex;
      gap: 6px;
      justify-content: flex-end;
      align-items: center;
    }
    .schedule-actions .text-button {
      min-height: 26px;
      padding: 0 8px;
    }
    .schedule-panel-header {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      color: var(--muted);
      font-size: 12px;
    }
    .schedule-panel-header strong {
      color: var(--text);
      font-size: 13px;
    }
    .schedule-table-wrap {
      overflow: auto;
      border: 1px solid var(--line-soft);
      border-radius: 6px;
    }
    .schedule-name {
      display: grid;
      gap: 3px;
      min-width: 150px;
    }
    .schedule-subline {
      color: var(--muted);
      font-size: 11px;
      font-weight: 500;
    }
    .schedule-editor-backdrop {
      position: fixed;
      inset: 0;
      z-index: 29;
      background: rgb(21 31 43 / 34%);
    }
    .schedule-editor-backdrop[hidden] { display: none; }
    .schedule-editor {
      position: fixed;
      top: 5vh;
      left: 50%;
      z-index: 30;
      width: min(720px, 94vw);
      max-height: 90vh;
      overflow: auto;
      transform: translateX(-50%);
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 24px 60px rgb(21 31 43 / 28%);
    }
    .schedule-editor[hidden] { display: none; }
    .schedule-editor-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
    }
    .schedule-editor-header h3 { margin: 0; font-size: 15px; }
    .schedule-editor form {
      display: grid;
      gap: 14px;
      padding: 16px;
    }
    .schedule-editor-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 10px;
    }
    .schedule-editor-field {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
      min-width: 0;
    }
    .schedule-editor-field input,
    .schedule-editor-field select {
      min-height: 32px;
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 9px;
      background: #fff;
      color: var(--text);
      font: inherit;
      font-size: 12px;
      text-transform: none;
    }
    .schedule-editor-field.checkbox-field {
      display: flex;
      flex-direction: row;
      gap: 8px;
      align-items: center;
      text-transform: none;
      color: var(--text);
      font-size: 12px;
    }
    .schedule-editor-field.checkbox-field input { width: auto; min-height: auto; }
    .schedule-editor-actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      align-items: center;
    }
    .schedule-editor-error {
      min-height: 18px;
      color: var(--red);
      font-size: 12px;
    }
    .task-table-wrap { overflow: auto; }
    .task-status {
      display: inline-flex;
      padding: 2px 7px;
      border-radius: 999px;
      background: #f1f5f9;
      color: var(--muted);
      font-weight: 800;
    }
    .task-status.running,
    .task-status.pending,
    .task-status.retrying,
    .task-status.enabled,
    .task-status.submitted {
      background: #eef5ff;
      color: #195bb8;
    }
    .task-status.failed,
    .task-status.error {
      background: #fff0ed;
      color: var(--red);
    }
    .task-status.success,
    .task-status.completed {
      background: #eef8f3;
      color: var(--green);
    }
    main {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
      padding: 18px 22px;
    }
    a {
      display: grid;
      gap: 8px;
      min-height: 120px;
      padding: 18px;
      color: inherit;
      text-decoration: none;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    a:hover { border-color: var(--blue); }
    main strong { font-size: 17px; }
    main span { color: var(--muted); font-size: 13px; line-height: 1.45; }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    th, td {
      padding: 8px 9px;
      border-bottom: 1px solid var(--line-soft);
      text-align: right;
      white-space: nowrap;
    }
    th:first-child, td:first-child,
    th:nth-child(2), td:nth-child(2) {
      text-align: left;
    }
    th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: #f8fafc;
      color: var(--muted);
    }
    .empty {
      padding: 22px 14px;
      color: var(--muted);
      text-align: center;
    }
    .drawer-pagination {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding: 10px 16px;
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
    }
    .pagination-actions {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    @media (max-width: 780px) {
      .data-monitor { grid-template-columns: 1fr; margin-left: 12px; margin-right: 12px; }
      .monitor-actions { justify-content: flex-start; }
      .data-monitor-meta { white-space: normal; }
      .drawer-filters { grid-template-columns: 1fr; }
      .drawer-pagination { align-items: flex-start; flex-direction: column; }
      header, main { padding-left: 12px; padding-right: 12px; }
    }
  </style>
</head>
<body>
  <script id="workbench-index-payload" type="application/json">__WORKBENCH_INDEX_PAYLOAD__</script>
  <header>
    <h1>Backtest Workbench</h1>
    <div class="subtitle">One local service for strategy results and market K-line inspection.</div>
  </header>
  <section class="data-monitor" id="dataSourceMonitor" hidden>
    <div class="data-monitor-title">Data Source</div>
    <div class="data-monitor-body">
      <div class="data-source-summary" id="dataSourceSummary"></div>
      <div class="data-source-summary" id="dataScheduleSummary"></div>
    </div>
    <div class="monitor-actions">
      <span class="data-monitor-meta" id="dataSourceMonitorMeta"></span>
      <button class="text-button" id="dataSourceDetailsButton" type="button">Details</button>
    </div>
  </section>
  <div class="drawer-backdrop" id="dataSourceDrawerBackdrop" hidden></div>
  <aside class="data-drawer" id="dataSourceDrawer" hidden aria-label="Data source task details">
    <div class="drawer-header">
      <div>
        <h2>Data Source Monitor</h2>
        <div class="subtitle">Schedule controls and crawl task monitor</div>
      </div>
      <button class="text-button" id="dataSourceDrawerCloseButton" type="button">Close</button>
    </div>
    <section class="schedule-panel" aria-label="Data source schedules">
      <div class="schedule-panel-header">
        <strong>Schedules</strong>
        <span id="dataScheduleMeta"></span>
      </div>
      <div class="schedule-table-wrap">
        <table>
          <thead>
            <tr>
              <th>Schedule</th>
              <th>Status</th>
              <th>Trigger</th>
              <th>Repeat</th>
              <th>Next Run</th>
              <th>Last Job</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody id="dataScheduleRows"></tbody>
        </table>
      </div>
    </section>
    <section class="schedule-panel schedule-runs-panel" aria-label="Recent schedule runs">
      <div class="schedule-panel-header">
        <strong>Recent Runs</strong>
        <span id="dataScheduleRunMeta"></span>
      </div>
      <div class="schedule-table-wrap">
        <table>
          <thead>
            <tr>
              <th>Schedule</th>
              <th>Target</th>
              <th>Run Status</th>
              <th>Job Status</th>
              <th>Triggered</th>
              <th>Job</th>
            </tr>
          </thead>
          <tbody id="dataScheduleRunRows"></tbody>
        </table>
      </div>
    </section>
    <div class="source-tabs" id="dataSourceTabs"></div>
    <div class="drawer-filters">
      <label class="filter-field">
        <span>Symbol</span>
        <input id="taskSymbolSearch" type="search" autocomplete="off">
      </label>
      <div class="filter-group">
        <span>Frequency</span>
        <div class="checkbox-pills" id="taskFrequencyFilters"></div>
      </div>
      <div class="filter-group">
        <span>Status</span>
        <div class="checkbox-pills" id="taskStatusFilters"></div>
      </div>
      <label class="filter-field">
        <span>Page Size</span>
        <select id="taskPageSizeSelect">
          <option value="25">25</option>
          <option value="50" selected>50</option>
          <option value="100">100</option>
        </select>
      </label>
    </div>
    <div class="drawer-meta" id="dataSourceDrawerMeta"></div>
    <div class="task-table-wrap">
      <table>
        <thead>
          <tr>
            <th>Source</th>
            <th>Symbol</th>
            <th>Frequency</th>
            <th>Adjust</th>
            <th>Status</th>
            <th>Attempts</th>
            <th>Updated</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody id="dataSourceTaskRows"></tbody>
      </table>
    </div>
    <div class="drawer-pagination">
      <span id="taskPaginationMeta"></span>
      <div class="pagination-actions">
        <button class="text-button" id="taskPreviousPageButton" type="button">Previous</button>
        <button class="text-button" id="taskNextPageButton" type="button">Next</button>
      </div>
    </div>
  </aside>
  <div class="schedule-editor-backdrop" id="scheduleEditBackdrop" hidden></div>
  <section class="schedule-editor" id="scheduleEditDialog" hidden aria-label="Edit schedule">
    <div class="schedule-editor-header">
      <div>
        <h3>Edit Schedule</h3>
        <div class="subtitle" id="scheduleEditSubtitle"></div>
      </div>
      <button class="text-button" id="scheduleEditCloseButton" type="button">Close</button>
    </div>
    <form id="scheduleEditForm">
      <div class="schedule-editor-grid">
        <label class="schedule-editor-field">
          <span>Name</span>
          <input id="scheduleEditName" type="text" autocomplete="off">
        </label>
        <label class="schedule-editor-field">
          <span>Source</span>
          <input id="scheduleEditSourceId" type="text" autocomplete="off">
        </label>
        <label class="schedule-editor-field">
          <span>Overlap</span>
          <select id="scheduleEditOverlapPolicy">
            <option value="skip">skip</option>
            <option value="allow">allow</option>
          </select>
        </label>
      </div>
      <div class="schedule-editor-grid">
        <label class="schedule-editor-field">
          <span>Trigger</span>
          <select id="scheduleEditTriggerType">
            <option value="interval">interval</option>
            <option value="daily">daily</option>
            <option value="weekly">weekly</option>
            <option value="once">once</option>
          </select>
        </label>
        <label class="schedule-editor-field">
          <span>Timezone</span>
          <input id="scheduleEditTimezone" type="text" autocomplete="off">
        </label>
        <label class="schedule-editor-field">
          <span>Every</span>
          <input id="scheduleEditEvery" type="number" min="1" step="1">
        </label>
        <label class="schedule-editor-field">
          <span>Unit</span>
          <select id="scheduleEditUnit">
            <option value="minutes">minutes</option>
            <option value="hours">hours</option>
            <option value="days">days</option>
          </select>
        </label>
        <label class="schedule-editor-field">
          <span>Time</span>
          <input id="scheduleEditTime" type="time">
        </label>
        <label class="schedule-editor-field">
          <span>Days</span>
          <input id="scheduleEditDaysOfWeek" type="text" autocomplete="off">
        </label>
        <label class="schedule-editor-field">
          <span>Start At</span>
          <input id="scheduleEditStartAt" type="text" autocomplete="off">
        </label>
        <label class="schedule-editor-field">
          <span>Run At</span>
          <input id="scheduleEditRunAt" type="text" autocomplete="off">
        </label>
      </div>
      <div class="schedule-editor-grid">
        <label class="schedule-editor-field">
          <span>Repeat</span>
          <select id="scheduleEditRepeatMode">
            <option value="forever">forever</option>
            <option value="count">count</option>
            <option value="until">until</option>
          </select>
        </label>
        <label class="schedule-editor-field">
          <span>Count</span>
          <input id="scheduleEditRepeatCount" type="number" min="1" step="1">
        </label>
        <label class="schedule-editor-field">
          <span>Until</span>
          <input id="scheduleEditRepeatUntil" type="text" autocomplete="off">
        </label>
      </div>
      <div class="schedule-editor-grid">
        <label class="schedule-editor-field">
          <span>Symbols</span>
          <input id="scheduleEditSymbols" type="text" autocomplete="off">
        </label>
        <label class="schedule-editor-field">
          <span>Frequencies</span>
          <input id="scheduleEditFrequencies" type="text" autocomplete="off">
        </label>
        <label class="schedule-editor-field">
          <span>Range</span>
          <select id="scheduleEditDateRangeType">
            <option value="last_n_days">last_n_days</option>
            <option value="fixed">fixed</option>
          </select>
        </label>
        <label class="schedule-editor-field">
          <span>Days</span>
          <input id="scheduleEditDateRangeDays" type="number" min="1" step="1">
        </label>
        <label class="schedule-editor-field">
          <span>Start Date</span>
          <input id="scheduleEditStartDate" type="date">
        </label>
        <label class="schedule-editor-field">
          <span>End Date</span>
          <input id="scheduleEditEndDate" type="date">
        </label>
        <label class="schedule-editor-field">
          <span>End Offset</span>
          <input id="scheduleEditEndOffsetDays" type="number" min="0" step="1">
        </label>
        <label class="schedule-editor-field">
          <span>Page Delay</span>
          <input id="scheduleEditPageDelaySeconds" type="number" min="0" step="0.05">
        </label>
        <label class="schedule-editor-field checkbox-field">
          <input id="scheduleEditRefreshExisting" type="checkbox">
          <span>Refresh existing coverage</span>
        </label>
      </div>
      <div class="schedule-editor-error" id="scheduleEditError"></div>
      <div class="schedule-editor-actions">
        <button class="text-button" id="scheduleEditDismissButton" type="button">Close</button>
        <button class="text-button" type="submit">Save</button>
      </div>
    </form>
  </section>
  <main>
    <a href="/strategy-results">
      <strong>Strategy Results</strong>
      <span>Review strategy runs, account curves, orders, and symbol drilldowns.</span>
    </a>
    <a href="/kline">
      <strong>K-line Viewer</strong>
      <span>Inspect cached market bars across configured data sources.</span>
    </a>
  </main>
  <script>
    const payload = JSON.parse(document.getElementById("workbench-index-payload").textContent);
    const DATA_MONITOR_REFRESH_MS = 10000;
    let dataMonitorTimer = null;
    let taskSearchTimer = null;
    let dataMonitorState = {
      sources: [],
      summariesBySource: {},
      jobs: [],
      schedules: [],
      scheduleRunsById: {},
      selectedSourceId: "",
      taskPagesBySource: {},
      filtersBySource: {},
      editingScheduleId: "",
      lastUpdated: "",
      error: "",
    };

    const escapeHtml = (value) => String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");

    function dataApiUrl(path) {
      const baseUrl = String(payload.data_api_base_url || "").replace(/\\/+$/, "");
      return baseUrl ? `${baseUrl}${path}` : path;
    }

    function dataApiRequestOptions() {
      const options = { cache: "no-store" };
      if (payload.data_api_token) {
        const headers = new Headers();
        headers.set("Authorization", `Bearer ${payload.data_api_token}`);
        options.headers = headers;
      }
      return options;
    }

    function dataApiMutationOptions(method, body) {
      const options = dataApiRequestOptions();
      options.method = method;
      if (body !== undefined) {
        const headers = new Headers(options.headers || undefined);
        headers.set("Content-Type", "application/json");
        options.headers = headers;
        options.body = JSON.stringify(body);
      }
      return options;
    }

    function dataMonitorEnabled() {
      return Boolean(payload.data_api_base_url);
    }

    function taskUpdatedAt(task) {
      return task.updated_at || task.finished_at || task.started_at || task.created_at || "";
    }

    function formatClock(value) {
      if (!value) return "";
      const date = value instanceof Date ? value : new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    }

    function sourceLabel(source) {
      return source.source_label || source.source_id || "Source";
    }

    function formatDateTime(value) {
      if (!value) return "";
      const date = value instanceof Date ? value : new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return date.toLocaleString([], {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    }

    function defaultTaskFilters() {
      return { symbol: "", frequencies: [], statuses: [], page: 1, pageSize: 50 };
    }

    function filtersForSource(sourceId) {
      if (!dataMonitorState.filtersBySource[sourceId]) {
        dataMonitorState.filtersBySource[sourceId] = defaultTaskFilters();
      }
      return dataMonitorState.filtersBySource[sourceId];
    }

    function sourceSummary(sourceId) {
      return dataMonitorState.summariesBySource[sourceId] || {
        total: 0,
        status_counts: {},
        frequency_counts: {},
        latest_updated_at: null,
      };
    }

    function selectedSource() {
      const sources = dataMonitorState.sources || [];
      const selectedId = dataMonitorState.selectedSourceId || sources[0]?.source_id || "";
      return sources.find((source) => source.source_id === selectedId) || sources[0] || null;
    }

    function sortedKeys(value) {
      return Object.keys(value || {}).sort((left, right) => left.localeCompare(right));
    }

    function scheduleList() {
      return Array.isArray(dataMonitorState.schedules) ? dataMonitorState.schedules : [];
    }

    function scheduleById(scheduleId) {
      return scheduleList().find((schedule) => schedule.schedule_id === scheduleId) || null;
    }

    function jobById(jobId) {
      const jobs = Array.isArray(dataMonitorState.jobs) ? dataMonitorState.jobs : [];
      return jobs.find((job) => job.job_id === jobId) || null;
    }

    function scheduleStatusCounts() {
      const counts = { total: 0, active: 0, due: 0, errors: 0, completed: 0 };
      const now = Date.now();
      for (const schedule of scheduleList()) {
        counts.total += 1;
        if (schedule.enabled && schedule.next_run_at) {
          counts.active += 1;
          const nextRunTime = new Date(schedule.next_run_at).getTime();
          if (!Number.isNaN(nextRunTime) && nextRunTime <= now) {
            counts.due += 1;
          }
        }
        if (schedule.status === "error") counts.errors += 1;
        if (schedule.status === "completed") counts.completed += 1;
      }
      return counts;
    }

    function scheduleConfig(schedule) {
      return schedule.config || {};
    }

    function formatScheduleJob(schedule) {
      const job = scheduleConfig(schedule).job || {};
      const symbols = Array.isArray(job.symbols) ? job.symbols : [];
      const symbolText = symbols.length <= 3 ? symbols.join(", ") : `${symbols.length} symbols`;
      const frequencies = Array.isArray(job.frequencies) ? job.frequencies.join(", ") : "";
      return [job.source_id, symbolText, frequencies].filter(Boolean).join(" · ");
    }

    function formatScheduleTrigger(schedule) {
      const trigger = scheduleConfig(schedule).trigger || {};
      let label = trigger.type || "unknown";
      if (trigger.type === "interval") {
        label = `Every ${trigger.every || 1} ${trigger.unit || "hours"}`;
      } else if (trigger.type === "daily") {
        label = `Daily ${trigger.time || ""}`.trim();
      } else if (trigger.type === "weekly") {
        const days = Array.isArray(trigger.days_of_week) ? trigger.days_of_week.join(", ") : "";
        label = `${days} ${trigger.time || ""}`.trim();
      } else if (trigger.type === "once") {
        label = `Once ${formatDateTime(trigger.run_at)}`.trim();
      }
      if (trigger.start_at) {
        label = `${label} · from ${formatDateTime(trigger.start_at)}`;
      }
      return label;
    }

    function formatScheduleRepeat(schedule) {
      const repeat = scheduleConfig(schedule).repeat || {};
      if (repeat.mode === "count") {
        return `${schedule.run_count || 0}/${repeat.count || 0} runs`;
      }
      if (repeat.mode === "until") {
        return `until ${formatDateTime(repeat.until)}`;
      }
      return repeat.mode || "forever";
    }

    function recentScheduleRuns() {
      const runsById = dataMonitorState.scheduleRunsById || {};
      const runs = [];
      for (const schedule of scheduleList()) {
        const scheduleRuns = Array.isArray(runsById[schedule.schedule_id])
          ? runsById[schedule.schedule_id]
          : [];
        for (const run of scheduleRuns) {
          runs.push({ ...run, schedule });
        }
      }
      return runs.sort((left, right) => {
        const leftTime = new Date(left.triggered_at || left.created_at || "").getTime();
        const rightTime = new Date(right.triggered_at || right.created_at || "").getTime();
        return (Number.isNaN(rightTime) ? 0 : rightTime) - (Number.isNaN(leftTime) ? 0 : leftTime);
      }).slice(0, 8);
    }

    function taskPageUrl(sourceId, filters) {
      const params = new URLSearchParams();
      params.set("source_id", sourceId);
      params.set("page", String(filters.page || 1));
      params.set("page_size", String(filters.pageSize || 50));
      if (filters.symbol.trim()) {
        params.set("symbol", filters.symbol.trim());
      }
      for (const frequency of filters.frequencies || []) {
        params.append("frequency", frequency);
      }
      for (const status of filters.statuses || []) {
        params.append("status", status);
      }
      return dataApiUrl(`/api/data/tasks?${params.toString()}`);
    }

    function renderScheduleSummary() {
      const summaryEl = document.getElementById("dataScheduleSummary");
      if (dataMonitorState.error) {
        summaryEl.innerHTML = `<span class="data-source-pill failed"><strong>Schedules</strong><span>offline</span></span>`;
        return;
      }
      const counts = scheduleStatusCounts();
      if (!counts.total) {
        summaryEl.innerHTML = `<span class="data-source-pill"><strong>Schedules</strong><span>0</span></span>`;
        return;
      }
      const css = counts.errors ? " failed" : counts.active ? " active" : "";
      summaryEl.innerHTML = `<span class="data-source-pill${css}">
        <strong>Schedules</strong>
        <span>total ${escapeHtml(counts.total)}</span>
        <span>active ${escapeHtml(counts.active)}</span>
        ${counts.due ? `<span>due ${escapeHtml(counts.due)}</span>` : ""}
        ${counts.errors ? `<span>errors ${escapeHtml(counts.errors)}</span>` : ""}
      </span>`;
    }

    function renderDataMonitor() {
      const monitor = document.getElementById("dataSourceMonitor");
      if (!dataMonitorEnabled()) {
        monitor.hidden = true;
        return;
      }
      monitor.hidden = false;
      const summaryEl = document.getElementById("dataSourceSummary");
      const metaEl = document.getElementById("dataSourceMonitorMeta");
      if (dataMonitorState.error) {
        summaryEl.innerHTML = `<span class="data-source-pill failed"><strong>Offline</strong><span>${escapeHtml(dataMonitorState.error)}</span></span>`;
        renderScheduleSummary();
        metaEl.textContent = dataMonitorState.lastUpdated ? `checked ${formatClock(dataMonitorState.lastUpdated)}` : "";
        renderTaskDrawer();
        return;
      }
      const sources = dataMonitorState.sources || [];
      summaryEl.innerHTML = sources.length ? sources.map((source) => {
        const counts = sourceSummary(source.source_id).status_counts || {};
        const active = (counts.running || 0) + (counts.pending || 0) + (counts.retrying || 0);
        const failed = counts.failed || 0;
        const success = counts.success || 0;
        const css = failed ? " failed" : active ? " active" : "";
        const stateText = active
          ? `running ${active}`
          : failed
            ? `failed ${failed}`
            : "idle";
        return `<span class="data-source-pill${css}">
          <strong>${escapeHtml(sourceLabel(source))}</strong>
          <span>${escapeHtml(stateText)}</span>
          <span>success ${escapeHtml(success)}</span>
          ${failed && active ? `<span>failed ${escapeHtml(failed)}</span>` : ""}
        </span>`;
      }).join("") : `<span class="data-source-pill"><strong>No sources</strong></span>`;
      renderScheduleSummary();
      metaEl.textContent = dataMonitorState.lastUpdated ? `updated ${formatClock(dataMonitorState.lastUpdated)}` : "";
      renderTaskDrawer();
    }

    function renderSourceTabs() {
      const tabsEl = document.getElementById("dataSourceTabs");
      const sources = dataMonitorState.sources || [];
      tabsEl.innerHTML = sources.map((source) => {
        const active = source.source_id === selectedSource()?.source_id ? " active" : "";
        return `<button class="source-tab${active}" data-source-id="${escapeHtml(source.source_id)}" type="button">${escapeHtml(sourceLabel(source))}</button>`;
      }).join("");
      for (const button of tabsEl.querySelectorAll(".source-tab")) {
        button.addEventListener("click", () => selectTaskSource(button.dataset.sourceId || ""));
      }
    }

    function renderFilterOptions(containerId, values, selectedValues, filterKey) {
      const container = document.getElementById(containerId);
      container.innerHTML = values.length ? values.map((value) => {
        const checked = selectedValues.includes(value) ? " checked" : "";
        return `<label class="checkbox-pill"><input type="checkbox" value="${escapeHtml(value)}"${checked}>${escapeHtml(value)}</label>`;
      }).join("") : `<span class="data-monitor-meta">All</span>`;
      for (const input of container.querySelectorAll("input")) {
        input.addEventListener("change", () => {
          const source = selectedSource();
          if (!source) return;
          const filters = filtersForSource(source.source_id);
          const selected = Array.from(container.querySelectorAll("input:checked")).map((item) => item.value);
          filters[filterKey] = selected;
          filters.page = 1;
          loadSelectedTaskPage();
        });
      }
    }

    function renderTaskControls() {
      const source = selectedSource();
      const symbolInput = document.getElementById("taskSymbolSearch");
      const pageSizeSelect = document.getElementById("taskPageSizeSelect");
      if (!source) {
        symbolInput.value = "";
        pageSizeSelect.value = "50";
        renderFilterOptions("taskFrequencyFilters", [], [], "frequencies");
        renderFilterOptions("taskStatusFilters", [], [], "statuses");
        return;
      }
      const filters = filtersForSource(source.source_id);
      const summary = sourceSummary(source.source_id);
      if (document.activeElement !== symbolInput) {
        symbolInput.value = filters.symbol || "";
      }
      pageSizeSelect.value = String(filters.pageSize || 50);
      renderFilterOptions(
        "taskFrequencyFilters",
        sortedKeys(summary.frequency_counts),
        filters.frequencies || [],
        "frequencies",
      );
      renderFilterOptions(
        "taskStatusFilters",
        sortedKeys(summary.status_counts),
        filters.statuses || [],
        "statuses",
      );
    }

    function renderScheduleRows() {
      const metaEl = document.getElementById("dataScheduleMeta");
      const rowsEl = document.getElementById("dataScheduleRows");
      if (dataMonitorState.error) {
        metaEl.textContent = "Schedules unavailable";
        rowsEl.innerHTML = `<tr><td class="empty" colspan="7">Unable to load schedules</td></tr>`;
        return;
      }
      const schedules = scheduleList();
      const counts = scheduleStatusCounts();
      metaEl.textContent = `${counts.total} schedules · ${counts.active} active · ${counts.completed} completed`;
      rowsEl.innerHTML = schedules.length ? schedules.map((schedule) => {
        const status = escapeHtml(schedule.status || (schedule.enabled ? "enabled" : "disabled"));
        const lastJob = schedule.last_job_id || "";
        const lastRun = schedule.last_run_at ? `last run ${formatDateTime(schedule.last_run_at)}` : "";
        const scheduleId = escapeHtml(schedule.schedule_id || "");
        const toggleText = schedule.enabled ? "Disable" : "Enable";
        return `<tr>
          <td>
            <div class="schedule-name">
              <strong>${escapeHtml(schedule.name || schedule.schedule_id || "")}</strong>
              <span class="schedule-subline">${escapeHtml(formatScheduleJob(schedule))}</span>
            </div>
          </td>
          <td><span class="task-status ${status}">${status}</span></td>
          <td>${escapeHtml(formatScheduleTrigger(schedule))}</td>
          <td>${escapeHtml(formatScheduleRepeat(schedule))}</td>
          <td>${escapeHtml(formatDateTime(schedule.next_run_at))}</td>
          <td>
            <div class="schedule-name">
              <strong>${escapeHtml(lastJob)}</strong>
              <span class="schedule-subline">${escapeHtml(lastRun)}</span>
            </div>
          </td>
          <td>
            <div class="schedule-actions">
              <button class="text-button" data-schedule-action="toggle" data-schedule-id="${scheduleId}" type="button">${toggleText}</button>
              <button class="text-button" data-schedule-action="run" data-schedule-id="${scheduleId}" type="button">Run</button>
              <button class="text-button" data-schedule-action="edit" data-schedule-id="${scheduleId}" type="button">Edit</button>
            </div>
          </td>
        </tr>`;
      }).join("") : `<tr><td class="empty" colspan="7">No schedules</td></tr>`;
      for (const button of rowsEl.querySelectorAll("[data-schedule-action]")) {
        button.addEventListener("click", () => {
          const scheduleId = button.dataset.scheduleId || "";
          if (button.dataset.scheduleAction === "toggle") {
            toggleSchedule(scheduleId);
          } else if (button.dataset.scheduleAction === "run") {
            runScheduleNow(scheduleId);
          } else if (button.dataset.scheduleAction === "edit") {
            openScheduleEditor(scheduleId);
          }
        });
      }
    }

    function scheduleEditInput(id) {
      return document.getElementById(id);
    }

    function inputValue(id) {
      return String(scheduleEditInput(id).value || "").trim();
    }

    function numberValue(id, fallback = null) {
      const value = inputValue(id);
      if (!value) {
        return fallback;
      }
      const parsed = Number(value);
      return Number.isFinite(parsed) ? parsed : fallback;
    }

    function listValue(id) {
      return inputValue(id)
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
    }

    function setInputValue(id, value) {
      scheduleEditInput(id).value = value ?? "";
    }

    function setScheduleEditError(message) {
      document.getElementById("scheduleEditError").textContent = message || "";
    }

    function setScheduleActionError(message) {
      const metaEl = document.getElementById("dataScheduleMeta");
      if (metaEl) {
        metaEl.textContent = message ? `Schedule update failed · ${message}` : "";
      }
    }

    function closeScheduleEditor() {
      dataMonitorState.editingScheduleId = "";
      document.getElementById("scheduleEditDialog").hidden = true;
      document.getElementById("scheduleEditBackdrop").hidden = true;
      setScheduleEditError("");
    }

    function openScheduleEditor(scheduleId) {
      const schedule = scheduleById(scheduleId);
      if (!schedule) {
        return;
      }
      const config = scheduleConfig(schedule);
      const trigger = config.trigger || {};
      const repeat = config.repeat || {};
      const job = config.job || {};
      const dateRange = job.date_range || {};
      dataMonitorState.editingScheduleId = schedule.schedule_id;
      document.getElementById("scheduleEditSubtitle").textContent = schedule.schedule_id || "";
      setInputValue("scheduleEditName", config.name || schedule.name || "");
      setInputValue("scheduleEditSourceId", job.source_id || "");
      setInputValue("scheduleEditOverlapPolicy", config.overlap_policy || "skip");
      setInputValue("scheduleEditTriggerType", trigger.type || "interval");
      setInputValue("scheduleEditTimezone", trigger.timezone || "Asia/Shanghai");
      setInputValue("scheduleEditEvery", trigger.every || 1);
      setInputValue("scheduleEditUnit", trigger.unit || "hours");
      setInputValue("scheduleEditTime", trigger.time || "");
      setInputValue(
        "scheduleEditDaysOfWeek",
        Array.isArray(trigger.days_of_week) ? trigger.days_of_week.join(", ") : "",
      );
      setInputValue("scheduleEditStartAt", trigger.start_at || "");
      setInputValue("scheduleEditRunAt", trigger.run_at || "");
      setInputValue("scheduleEditRepeatMode", repeat.mode || "forever");
      setInputValue("scheduleEditRepeatCount", repeat.count || "");
      setInputValue("scheduleEditRepeatUntil", repeat.until || "");
      setInputValue("scheduleEditSymbols", Array.isArray(job.symbols) ? job.symbols.join(", ") : "");
      setInputValue(
        "scheduleEditFrequencies",
        Array.isArray(job.frequencies) ? job.frequencies.join(", ") : "",
      );
      setInputValue("scheduleEditDateRangeType", dateRange.type || "last_n_days");
      setInputValue("scheduleEditDateRangeDays", dateRange.days || 1);
      setInputValue("scheduleEditStartDate", dateRange.start_date || "");
      setInputValue("scheduleEditEndDate", dateRange.end_date || "");
      setInputValue("scheduleEditEndOffsetDays", dateRange.end_offset_days || 0);
      setInputValue("scheduleEditPageDelaySeconds", job.page_delay_seconds || 0);
      scheduleEditInput("scheduleEditRefreshExisting").checked = job.refresh_existing !== false;
      setScheduleEditError("");
      document.getElementById("scheduleEditBackdrop").hidden = false;
      document.getElementById("scheduleEditDialog").hidden = false;
    }

    function buildScheduleEditPayload(schedule) {
      const config = scheduleConfig(schedule);
      const triggerType = inputValue("scheduleEditTriggerType") || "interval";
      const trigger = {
        type: triggerType,
        timezone: inputValue("scheduleEditTimezone") || "Asia/Shanghai",
      };
      const startAt = inputValue("scheduleEditStartAt");
      if (startAt) {
        trigger.start_at = startAt;
      } else {
        trigger.start_at = null;
      }
      if (triggerType === "once") {
        trigger.run_at = inputValue("scheduleEditRunAt") || null;
      } else if (triggerType === "interval") {
        trigger.every = numberValue("scheduleEditEvery", 1);
        trigger.unit = inputValue("scheduleEditUnit") || "hours";
      } else if (triggerType === "daily") {
        trigger.time = inputValue("scheduleEditTime") || "00:00";
      } else if (triggerType === "weekly") {
        trigger.time = inputValue("scheduleEditTime") || "00:00";
        trigger.days_of_week = listValue("scheduleEditDaysOfWeek");
      }

      const repeatMode = inputValue("scheduleEditRepeatMode") || "forever";
      const repeat = { mode: repeatMode };
      if (repeatMode === "count") {
        repeat.count = numberValue("scheduleEditRepeatCount", 1);
      } else if (repeatMode === "until") {
        repeat.until = inputValue("scheduleEditRepeatUntil") || null;
      }

      const dateRangeType = inputValue("scheduleEditDateRangeType") || "last_n_days";
      const dateRange = {
        type: dateRangeType,
        end_offset_days: numberValue("scheduleEditEndOffsetDays", 0),
      };
      if (dateRangeType === "fixed") {
        dateRange.start_date = inputValue("scheduleEditStartDate") || null;
        dateRange.end_date = inputValue("scheduleEditEndDate") || null;
      } else {
        dateRange.days = numberValue("scheduleEditDateRangeDays", 1);
      }

      return {
        name: inputValue("scheduleEditName") || config.name || schedule.name,
        trigger,
        repeat,
        job: {
          source_id: inputValue("scheduleEditSourceId") || config.job?.source_id || "",
          symbols: listValue("scheduleEditSymbols"),
          frequencies: listValue("scheduleEditFrequencies"),
          date_range: dateRange,
          page_delay_seconds: numberValue("scheduleEditPageDelaySeconds", 0),
          refresh_existing: scheduleEditInput("scheduleEditRefreshExisting").checked,
        },
        overlap_policy: inputValue("scheduleEditOverlapPolicy") || "skip",
      };
    }

    async function readApiError(response) {
      try {
        const errorPayload = await response.json();
        return errorPayload.error || errorPayload.message || `HTTP ${response.status}`;
      } catch (error) {
        return `HTTP ${response.status}`;
      }
    }

    async function toggleSchedule(scheduleId) {
      const schedule = scheduleById(scheduleId);
      if (!schedule) {
        return;
      }
      setScheduleActionError("");
      try {
        const response = await fetch(dataApiUrl(`/api/data/schedules/${encodeURIComponent(schedule.schedule_id)}/${schedule.enabled ? "disable" : "enable"}`), dataApiMutationOptions("POST"));
        if (!response.ok) {
          setScheduleActionError(await readApiError(response));
          return;
        }
        await loadDataMonitor();
      } catch (error) {
        setScheduleActionError(error.message);
      }
    }

    async function runScheduleNow(scheduleId) {
      const schedule = scheduleById(scheduleId);
      if (!schedule) {
        return;
      }
      setScheduleActionError("");
      try {
        const response = await fetch(dataApiUrl(`/api/data/schedules/${encodeURIComponent(schedule.schedule_id)}/run-now`), dataApiMutationOptions("POST"));
        if (!response.ok) {
          setScheduleActionError(await readApiError(response));
          return;
        }
        await loadDataMonitor();
      } catch (error) {
        setScheduleActionError(error.message);
      }
    }

    async function saveScheduleEdits(event) {
      event.preventDefault();
      const schedule = scheduleById(dataMonitorState.editingScheduleId);
      if (!schedule) {
        closeScheduleEditor();
        return;
      }
      const payload = buildScheduleEditPayload(schedule);
      setScheduleEditError("");
      try {
        const response = await fetch(dataApiUrl(`/api/data/schedules/${encodeURIComponent(schedule.schedule_id)}`), dataApiMutationOptions("PATCH", payload));
        if (!response.ok) {
          setScheduleEditError(await readApiError(response));
          return;
        }
        closeScheduleEditor();
        await loadDataMonitor();
      } catch (error) {
        setScheduleEditError(error.message);
      }
    }

    function renderScheduleRunRows() {
      const metaEl = document.getElementById("dataScheduleRunMeta");
      const rowsEl = document.getElementById("dataScheduleRunRows");
      if (dataMonitorState.error) {
        metaEl.textContent = "Run history unavailable";
        rowsEl.innerHTML = `<tr><td class="empty" colspan="6">Unable to load schedule runs</td></tr>`;
        return;
      }
      const runs = recentScheduleRuns();
      metaEl.textContent = runs.length ? `${runs.length} latest runs` : "No run history";
      rowsEl.innerHTML = runs.length ? runs.map((run) => {
        const schedule = run.schedule || scheduleById(run.schedule_id) || {};
        const job = run.job_id ? jobById(run.job_id) : null;
        const runStatus = escapeHtml(run.status || "unknown");
        const jobStatus = escapeHtml(job?.status || (run.job_id ? "submitted" : ""));
        const jobLine = job
          ? `${job.success_count || 0}/${job.total_items || 0} ok · failed ${job.failed_count || 0}`
          : run.error || "";
        return `<tr>
          <td>
            <div class="schedule-name">
              <strong>${escapeHtml(schedule.name || run.schedule_id || "")}</strong>
              <span class="schedule-subline">${escapeHtml(schedule.schedule_id || "")}</span>
            </div>
          </td>
          <td>${escapeHtml(formatScheduleJob(schedule))}</td>
          <td><span class="task-status ${runStatus}">${runStatus}</span></td>
          <td>${jobStatus ? `<span class="task-status ${jobStatus}">${jobStatus}</span>` : ""}</td>
          <td>${escapeHtml(formatDateTime(run.triggered_at))}</td>
          <td>
            <div class="schedule-name">
              <strong>${escapeHtml(run.job_id || "")}</strong>
              <span class="schedule-subline">${escapeHtml(jobLine)}</span>
            </div>
          </td>
        </tr>`;
      }).join("") : `<tr><td class="empty" colspan="6">No schedule runs yet</td></tr>`;
    }

    function renderTaskDrawer() {
      renderScheduleRows();
      renderScheduleRunRows();
      renderSourceTabs();
      renderTaskControls();
      const metaEl = document.getElementById("dataSourceDrawerMeta");
      const rowsEl = document.getElementById("dataSourceTaskRows");
      const paginationMetaEl = document.getElementById("taskPaginationMeta");
      const previousButton = document.getElementById("taskPreviousPageButton");
      const nextButton = document.getElementById("taskNextPageButton");
      if (dataMonitorState.error) {
        metaEl.textContent = `Data source monitor offline · ${dataMonitorState.error}`;
        paginationMetaEl.textContent = "";
        previousButton.disabled = true;
        nextButton.disabled = true;
        rowsEl.innerHTML = `<tr><td class="empty" colspan="8">Unable to load crawl tasks</td></tr>`;
        return;
      }
      const source = selectedSource();
      if (!source) {
        metaEl.textContent = "No data sources";
        paginationMetaEl.textContent = "";
        previousButton.disabled = true;
        nextButton.disabled = true;
        rowsEl.innerHTML = `<tr><td class="empty" colspan="8">No crawl tasks</td></tr>`;
        return;
      }
      const page = dataMonitorState.taskPagesBySource[source.source_id] || {
        tasks: [],
        page: filtersForSource(source.source_id).page,
        page_size: filtersForSource(source.source_id).pageSize,
        total: sourceSummary(source.source_id).total || 0,
        total_pages: 1,
      };
      const tasks = page.tasks || [];
      const jobs = Array.isArray(dataMonitorState.jobs) ? dataMonitorState.jobs.length : 0;
      const schedules = scheduleList().length;
      metaEl.textContent = `${escapeHtml(sourceLabel(source))} · ${page.total || 0} matching tasks · ${jobs} submitted jobs · ${schedules} schedules`;
      paginationMetaEl.textContent = `Page ${page.page || 1} / ${page.total_pages || 1} · ${page.total || 0} total`;
      previousButton.disabled = (page.page || 1) <= 1;
      nextButton.disabled = (page.page || 1) >= (page.total_pages || 1);
      rowsEl.innerHTML = tasks.length ? tasks.map((task) => {
        const status = escapeHtml(task.status || "unknown");
        return `<tr>
          <td>${escapeHtml(sourceLabel(source))}</td>
          <td>${escapeHtml(task.symbol || "")}</td>
          <td>${escapeHtml(task.frequency || "")}</td>
          <td>${escapeHtml(task.adjust || "")}</td>
          <td><span class="task-status ${status}">${status}</span></td>
          <td>${escapeHtml(task.attempts ?? "")}</td>
          <td>${escapeHtml(formatClock(taskUpdatedAt(task)))}</td>
          <td>${escapeHtml(task.last_error || "")}</td>
        </tr>`;
      }).join("") : `<tr><td class="empty" colspan="8">No matching crawl tasks</td></tr>`;
    }

    async function loadSelectedTaskPage() {
      const source = selectedSource();
      if (!dataMonitorEnabled() || !source) {
        renderTaskDrawer();
        return;
      }
      const filters = filtersForSource(source.source_id);
      try {
        const response = await fetch(taskPageUrl(source.source_id, filters), dataApiRequestOptions());
        if (!response.ok) {
          throw new Error(`${sourceLabel(source)} HTTP ${response.status}`);
        }
        const pagePayload = await response.json();
        dataMonitorState.taskPagesBySource = {
          ...dataMonitorState.taskPagesBySource,
          [source.source_id]: pagePayload,
        };
        filters.page = pagePayload.page || filters.page;
        filters.pageSize = pagePayload.page_size || filters.pageSize;
      } catch (error) {
        dataMonitorState = {
          ...dataMonitorState,
          lastUpdated: new Date(),
          error: error.message,
        };
      }
      renderDataMonitor();
    }

    function selectTaskSource(sourceId) {
      if (!sourceId || dataMonitorState.selectedSourceId === sourceId) {
        return;
      }
      dataMonitorState.selectedSourceId = sourceId;
      filtersForSource(sourceId);
      renderTaskDrawer();
      loadSelectedTaskPage();
    }

    async function loadDataMonitor() {
      if (!dataMonitorEnabled()) {
        renderDataMonitor();
        return;
      }
      try {
        const sourcesResponse = await fetch(dataApiUrl("/api/data-sources"), dataApiRequestOptions());
        if (!sourcesResponse.ok) {
          throw new Error(`HTTP ${sourcesResponse.status}`);
        }
        const sourcePayload = await sourcesResponse.json();
        const sources = Array.isArray(sourcePayload.sources) ? sourcePayload.sources : [];
        const summaryEntries = await Promise.all(sources.map(async (source) => {
          const response = await fetch(dataApiUrl(`/api/data/tasks/summary?source_id=${encodeURIComponent(source.source_id)}`), dataApiRequestOptions());
          if (!response.ok) {
            throw new Error(`${sourceLabel(source)} HTTP ${response.status}`);
          }
          const summaryPayload = await response.json();
          return [source.source_id, summaryPayload];
        }));
        let jobs = [];
        const jobsResponse = await fetch(dataApiUrl("/api/data/jobs"), dataApiRequestOptions());
        if (jobsResponse.ok) {
          const jobsPayload = await jobsResponse.json();
          jobs = Array.isArray(jobsPayload.jobs) ? jobsPayload.jobs : [];
        }
        let schedules = [];
        const schedulesResponse = await fetch(dataApiUrl("/api/data/schedules"), dataApiRequestOptions());
        if (schedulesResponse.ok) {
          const schedulesPayload = await schedulesResponse.json();
          schedules = Array.isArray(schedulesPayload.schedules) ? schedulesPayload.schedules : [];
        }
        let scheduleRunsById = {};
        const runEntries = await Promise.all(schedules.map(async (schedule) => {
          const response = await fetch(dataApiUrl(`/api/data/schedules/${encodeURIComponent(schedule.schedule_id)}/runs`), dataApiRequestOptions());
          if (!response.ok) {
            return [schedule.schedule_id, []];
          }
          const runsPayload = await response.json();
          return [schedule.schedule_id, Array.isArray(runsPayload.runs) ? runsPayload.runs : []];
        }));
        scheduleRunsById = Object.fromEntries(runEntries);
        const selectedSourceId = sources.some((source) => source.source_id === dataMonitorState.selectedSourceId)
          ? dataMonitorState.selectedSourceId
          : sources[0]?.source_id || "";
        dataMonitorState = {
          ...dataMonitorState,
          sources,
          summariesBySource: Object.fromEntries(summaryEntries),
          jobs,
          schedules,
          scheduleRunsById,
          selectedSourceId,
          lastUpdated: new Date(),
          error: "",
        };
      } catch (error) {
        dataMonitorState = {
          ...dataMonitorState,
          lastUpdated: new Date(),
          error: error.message,
        };
      }
      renderDataMonitor();
      if (!document.getElementById("dataSourceDrawer").hidden) {
        await loadSelectedTaskPage();
      }
    }

    function refreshDataMonitorWhenVisible() {
      if (!document.hidden) {
        loadDataMonitor();
      }
    }

    function startDataMonitor() {
      if (!dataMonitorEnabled()) {
        renderDataMonitor();
        return;
      }
      if (dataMonitorTimer) {
        clearInterval(dataMonitorTimer);
      }
      loadDataMonitor();
      dataMonitorTimer = setInterval(refreshDataMonitorWhenVisible, DATA_MONITOR_REFRESH_MS);
    }

    function openDataSourceDrawer() {
      document.getElementById("dataSourceDrawer").hidden = false;
      document.getElementById("dataSourceDrawerBackdrop").hidden = false;
      const source = selectedSource();
      if (source && !dataMonitorState.taskPagesBySource[source.source_id]) {
        loadSelectedTaskPage();
      } else {
        renderTaskDrawer();
      }
    }

    function closeDataSourceDrawer() {
      document.getElementById("dataSourceDrawer").hidden = true;
      document.getElementById("dataSourceDrawerBackdrop").hidden = true;
    }

    document.getElementById("dataSourceDetailsButton").addEventListener("click", openDataSourceDrawer);
    document.getElementById("dataSourceDrawerCloseButton").addEventListener("click", closeDataSourceDrawer);
    document.getElementById("dataSourceDrawerBackdrop").addEventListener("click", closeDataSourceDrawer);
    document.getElementById("scheduleEditForm").addEventListener("submit", saveScheduleEdits);
    document.getElementById("scheduleEditCloseButton").addEventListener("click", closeScheduleEditor);
    document.getElementById("scheduleEditDismissButton").addEventListener("click", closeScheduleEditor);
    document.getElementById("scheduleEditBackdrop").addEventListener("click", closeScheduleEditor);
    document.getElementById("taskSymbolSearch").addEventListener("input", (event) => {
      const source = selectedSource();
      if (!source) return;
      const filters = filtersForSource(source.source_id);
      filters.symbol = event.target.value || "";
      filters.page = 1;
      if (taskSearchTimer) {
        clearTimeout(taskSearchTimer);
      }
      taskSearchTimer = setTimeout(loadSelectedTaskPage, 300);
    });
    document.getElementById("taskPageSizeSelect").addEventListener("change", (event) => {
      const source = selectedSource();
      if (!source) return;
      const filters = filtersForSource(source.source_id);
      filters.pageSize = Number(event.target.value) || 50;
      filters.page = 1;
      loadSelectedTaskPage();
    });
    document.getElementById("taskPreviousPageButton").addEventListener("click", () => {
      const source = selectedSource();
      if (!source) return;
      const filters = filtersForSource(source.source_id);
      filters.page = Math.max(1, (filters.page || 1) - 1);
      loadSelectedTaskPage();
    });
    document.getElementById("taskNextPageButton").addEventListener("click", () => {
      const source = selectedSource();
      if (!source) return;
      const filters = filtersForSource(source.source_id);
      const page = dataMonitorState.taskPagesBySource[source.source_id];
      filters.page = Math.min(page?.total_pages || ((filters.page || 1) + 1), (filters.page || 1) + 1);
      loadSelectedTaskPage();
    });
    document.addEventListener("visibilitychange", refreshDataMonitorWhenVisible);
    startDataMonitor();
  </script>
</body>
</html>
""".replace("__WORKBENCH_INDEX_PAYLOAD__", safe_payload)
