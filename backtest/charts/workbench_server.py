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
) -> None:
    kline_service = KlineCacheService(sources=kline_sources)
    strategy_service = StrategyResultsService(results_roots=results_roots, bars_root=bars_root)
    normalized_data_api_base_url = data_api_base_url.rstrip("/") if data_api_base_url else None
    index_html = render_workbench_index_html(data_api_base_url=normalized_data_api_base_url).encode("utf-8")
    kline_html = render_kline_viewer_html(
        build_kline_shell_payload(
            default_window_size=default_window_size,
            data_api_base_url=normalized_data_api_base_url,
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
) -> dict:
    payload = {
        "mode": "dynamic",
        "default_window_size": default_window_size,
        "links": {"workbench_home": "/"},
    }
    if data_api_base_url:
        payload["data_api_base_url"] = data_api_base_url.rstrip("/")
    return payload


def render_workbench_index_html(data_api_base_url: str | None = None) -> str:
    payload = {}
    if data_api_base_url:
        payload["data_api_base_url"] = data_api_base_url.rstrip("/")
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
      grid-template-rows: auto auto minmax(0, 1fr);
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
    .task-status.retrying {
      background: #eef5ff;
      color: #195bb8;
    }
    .task-status.failed {
      background: #fff0ed;
      color: var(--red);
    }
    .task-status.success {
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
    @media (max-width: 780px) {
      .data-monitor { grid-template-columns: 1fr; margin-left: 12px; margin-right: 12px; }
      .monitor-actions { justify-content: flex-start; }
      .data-monitor-meta { white-space: normal; }
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
    <div class="data-source-summary" id="dataSourceSummary"></div>
    <div class="monitor-actions">
      <span class="data-monitor-meta" id="dataSourceMonitorMeta"></span>
      <button class="text-button" id="dataSourceDetailsButton" type="button">Details</button>
    </div>
  </section>
  <div class="drawer-backdrop" id="dataSourceDrawerBackdrop" hidden></div>
  <aside class="data-drawer" id="dataSourceDrawer" hidden aria-label="Data source task details">
    <div class="drawer-header">
      <div>
        <h2>Data Source Tasks</h2>
        <div class="subtitle">Read-only crawl task monitor</div>
      </div>
      <button class="text-button" id="dataSourceDrawerCloseButton" type="button">Close</button>
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
  </aside>
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
    let dataMonitorState = {
      sources: [],
      tasksBySource: {},
      jobs: [],
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

    function dataMonitorEnabled() {
      return Boolean(payload.data_api_base_url);
    }

    function statusCounts(tasks) {
      return tasks.reduce((counts, task) => {
        const status = String(task.status || "unknown");
        counts[status] = (counts[status] || 0) + 1;
        return counts;
      }, {});
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
        metaEl.textContent = dataMonitorState.lastUpdated ? `checked ${formatClock(dataMonitorState.lastUpdated)}` : "";
        renderTaskDrawer();
        return;
      }
      const sources = dataMonitorState.sources || [];
      summaryEl.innerHTML = sources.length ? sources.map((source) => {
        const tasks = dataMonitorState.tasksBySource[source.source_id] || [];
        const counts = statusCounts(tasks);
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
      metaEl.textContent = dataMonitorState.lastUpdated ? `updated ${formatClock(dataMonitorState.lastUpdated)}` : "";
      renderTaskDrawer();
    }

    function allMonitorTasks() {
      return (dataMonitorState.sources || []).flatMap((source) => {
        const tasks = dataMonitorState.tasksBySource[source.source_id] || [];
        return tasks.map((task) => ({ ...task, source_label: sourceLabel(source), source_id: source.source_id }));
      }).sort((left, right) => String(taskUpdatedAt(right)).localeCompare(String(taskUpdatedAt(left))));
    }

    function renderTaskDrawer() {
      const metaEl = document.getElementById("dataSourceDrawerMeta");
      const rowsEl = document.getElementById("dataSourceTaskRows");
      if (dataMonitorState.error) {
        metaEl.textContent = `Data source monitor offline · ${dataMonitorState.error}`;
        rowsEl.innerHTML = `<tr><td class="empty" colspan="8">Unable to load crawl tasks</td></tr>`;
        return;
      }
      const tasks = allMonitorTasks();
      const failed = tasks.filter((task) => task.status === "failed").length;
      const active = tasks.filter((task) => ["pending", "running", "retrying"].includes(task.status)).length;
      const jobs = Array.isArray(dataMonitorState.jobs) ? dataMonitorState.jobs.length : 0;
      metaEl.textContent = `${tasks.length} tasks · ${active} active · ${failed} failed · ${jobs} submitted jobs`;
      rowsEl.innerHTML = tasks.length ? tasks.map((task) => {
        const status = escapeHtml(task.status || "unknown");
        return `<tr>
          <td>${escapeHtml(task.source_label || task.source_id || "")}</td>
          <td>${escapeHtml(task.symbol || "")}</td>
          <td>${escapeHtml(task.frequency || "")}</td>
          <td>${escapeHtml(task.adjust || "")}</td>
          <td><span class="task-status ${status}">${status}</span></td>
          <td>${escapeHtml(task.attempts ?? "")}</td>
          <td>${escapeHtml(formatClock(taskUpdatedAt(task)))}</td>
          <td>${escapeHtml(task.last_error || "")}</td>
        </tr>`;
      }).join("") : `<tr><td class="empty" colspan="8">No crawl tasks</td></tr>`;
    }

    async function loadDataMonitor() {
      if (!dataMonitorEnabled()) {
        renderDataMonitor();
        return;
      }
      try {
        const sourcesResponse = await fetch(dataApiUrl("/api/data-sources"), { cache: "no-store" });
        if (!sourcesResponse.ok) {
          throw new Error(`HTTP ${sourcesResponse.status}`);
        }
        const sourcePayload = await sourcesResponse.json();
        const sources = Array.isArray(sourcePayload.sources) ? sourcePayload.sources : [];
        const taskEntries = await Promise.all(sources.map(async (source) => {
          const response = await fetch(dataApiUrl(`/api/data/tasks?source_id=${encodeURIComponent(source.source_id)}`), { cache: "no-store" });
          if (!response.ok) {
            throw new Error(`${sourceLabel(source)} HTTP ${response.status}`);
          }
          const taskPayload = await response.json();
          return [source.source_id, Array.isArray(taskPayload.tasks) ? taskPayload.tasks : []];
        }));
        let jobs = [];
        const jobsResponse = await fetch(dataApiUrl("/api/data/jobs"), { cache: "no-store" });
        if (jobsResponse.ok) {
          const jobsPayload = await jobsResponse.json();
          jobs = Array.isArray(jobsPayload.jobs) ? jobsPayload.jobs : [];
        }
        dataMonitorState = {
          sources,
          tasksBySource: Object.fromEntries(taskEntries),
          jobs,
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
    }

    function closeDataSourceDrawer() {
      document.getElementById("dataSourceDrawer").hidden = true;
      document.getElementById("dataSourceDrawerBackdrop").hidden = true;
    }

    document.getElementById("dataSourceDetailsButton").addEventListener("click", openDataSourceDrawer);
    document.getElementById("dataSourceDrawerCloseButton").addEventListener("click", closeDataSourceDrawer);
    document.getElementById("dataSourceDrawerBackdrop").addEventListener("click", closeDataSourceDrawer);
    document.addEventListener("visibilitychange", refreshDataMonitorWhenVisible);
    startDataMonitor();
  </script>
</body>
</html>
""".replace("__WORKBENCH_INDEX_PAYLOAD__", safe_payload)
