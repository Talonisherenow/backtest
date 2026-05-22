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
    instrument_html = render_instrument_manager_html(
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
            if parsed.path == "/instruments":
                self._send_bytes(instrument_html, "text/html; charset=utf-8")
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


def render_instrument_manager_html(
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
  <title>Instrument Lists - Backtest Workbench</title>
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
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 22px;
      background: var(--surface);
      border-bottom: 1px solid var(--line);
    }
    h1, h2, h3 { margin: 0; }
    h1 { font-size: 22px; }
    h2 { font-size: 15px; }
    h3 { font-size: 14px; }
    .title-block {
      min-width: 0;
      flex: 1 1 auto;
    }
    .header-actions {
      display: grid;
      justify-items: end;
      gap: 10px;
      flex: 0 0 auto;
    }
    .home-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      padding: 0 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--blue);
      font-size: 13px;
      font-weight: 800;
      text-decoration: none;
      white-space: nowrap;
    }
    .home-link:hover {
      border-color: #b8c7d6;
      background: #f8fafc;
    }
    button,
    input,
    select,
    textarea {
      font: inherit;
    }
    button {
      min-height: 30px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--blue);
      font-size: 12px;
      font-weight: 800;
      cursor: pointer;
      white-space: nowrap;
    }
    button:hover { background: #f8fafc; border-color: #b8c7d6; }
    button.primary { background: var(--blue); border-color: var(--blue); color: #fff; }
    button.danger { color: var(--red); border-color: #f1b8ad; background: #fff7f5; }
    input,
    select,
    textarea {
      width: 100%;
      min-height: 32px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      padding: 6px 8px;
      font-size: 12px;
    }
    textarea { min-height: 68px; resize: vertical; }
    .subtitle { color: var(--muted); font-size: 12px; margin-top: 4px; }
    .shell {
      display: grid;
      grid-template-rows: minmax(0, 1fr);
      min-height: calc(100vh - 65px);
      padding: 16px 22px 20px;
    }
    .workspace {
      display: grid;
      grid-template-columns: 220px minmax(420px, 1fr) 300px;
      min-height: 0;
      gap: 14px;
    }
    .panel {
      min-height: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      overflow: hidden;
    }
    .panel-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding: 12px;
      border-bottom: 1px solid var(--line-soft);
    }
    .panel-body {
      padding: 12px;
      min-height: 0;
    }
    .tag-list {
      display: grid;
      gap: 7px;
      max-height: calc(100vh - 250px);
      overflow: auto;
    }
    .tag-item {
      display: flex;
      justify-content: space-between;
      gap: 8px;
      align-items: center;
      min-height: 34px;
      padding: 7px 8px;
      border: 1px solid var(--line-soft);
      border-radius: 6px;
      background: #fbfdff;
      color: var(--text);
      text-align: left;
      white-space: normal;
    }
    .tag-item.active { border-color: #b7d4ff; background: #f4f8ff; }
    .tag-count { color: var(--muted); font-size: 12px; font-weight: 800; }
    .table-panel {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
    }
    .filters {
      display: grid;
      grid-template-columns: 1fr 130px 120px auto;
      gap: 8px;
      padding: 12px;
      border-bottom: 1px solid var(--line-soft);
    }
    .table-wrap {
      min-height: 0;
      overflow: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    th, td {
      padding: 9px 10px;
      border-bottom: 1px solid var(--line-soft);
      text-align: left;
      white-space: nowrap;
    }
    th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: #f8fafc;
      color: var(--muted);
    }
    tr.selected td { background: #f4f8ff; }
    .tag-chip {
      display: inline-flex;
      align-items: center;
      min-height: 22px;
      margin: 0 4px 4px 0;
      padding: 0 7px;
      border-radius: 999px;
      background: #eef5ff;
      color: #195bb8;
      font-size: 11px;
      font-weight: 800;
    }
    .empty {
      padding: 24px;
      color: var(--muted);
      text-align: center;
    }
    .detail-grid {
      display: grid;
      gap: 10px;
    }
    .detail-row {
      display: grid;
      grid-template-columns: 88px 1fr;
      gap: 8px;
      font-size: 12px;
    }
    .detail-row span:first-child { color: var(--muted); }
    .form-grid {
      display: grid;
      gap: 8px;
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid var(--line-soft);
    }
    .form-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .error {
      min-height: 18px;
      color: var(--red);
      font-size: 12px;
      font-weight: 700;
    }
    .modal-dialog {
      width: min(420px, calc(100vw - 32px));
      padding: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      color: var(--text);
      box-shadow: 0 18px 52px rgba(29, 39, 51, 0.18);
    }
    .modal-dialog::backdrop { background: rgba(29, 39, 51, 0.28); }
    .modal-card { margin: 0; }
    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 12px;
      border-bottom: 1px solid var(--line-soft);
    }
    .modal-body {
      display: grid;
      gap: 8px;
      padding: 12px;
    }
    .modal-actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      padding: 12px;
      border-top: 1px solid var(--line-soft);
    }
    @media (max-width: 1050px) {
      .workspace { grid-template-columns: 1fr; }
      .filters { grid-template-columns: 1fr 1fr; }
      .tag-list { max-height: none; }
    }
    @media (max-width: 680px) {
      header { align-items: flex-start; flex-direction: column; }
      .header-actions { justify-items: start; }
      .shell { padding-left: 12px; padding-right: 12px; }
      .filters, .form-row { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <script id="instrument-manager-payload" type="application/json">__INSTRUMENT_MANAGER_PAYLOAD__</script>
  <header>
    <div class="title-block">
      <h1>Instrument Lists</h1>
      <div class="subtitle">Backtest Workbench</div>
    </div>
    <div class="header-actions">
      <a class="home-link" href="/">Workbench Home</a>
    </div>
  </header>
  <section class="shell">
    <section class="workspace">
      <aside class="panel">
        <div class="panel-header">
          <div>
            <h2>Lists</h2>
            <div class="subtitle" id="tagMeta"></div>
          </div>
          <button id="openTagDialogButton" type="button">New List</button>
        </div>
        <div class="panel-body">
          <div class="tag-list" id="instrumentTagList"></div>
        </div>
      </aside>
      <section class="panel table-panel">
        <div class="filters">
          <input id="instrumentSearchInput" type="search" autocomplete="off" placeholder="Search symbol or name">
          <select id="instrumentSourceFilter"></select>
          <select id="instrumentTagFilter"></select>
          <button id="instrumentRefreshButton" type="button">Refresh</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Instrument</th>
                <th>Name</th>
                <th>Source</th>
                <th>Market</th>
                <th>Lists</th>
              </tr>
            </thead>
            <tbody id="instrumentRows"></tbody>
          </table>
        </div>
      </section>
      <aside class="panel">
        <div class="panel-header">
          <div>
            <h2>Details</h2>
            <div class="subtitle" id="instrumentDetailMeta"></div>
          </div>
          <button class="danger" id="deleteInstrumentButton" type="button">Delete</button>
        </div>
        <div class="panel-body">
          <div class="detail-grid" id="instrumentDetail"></div>
          <form class="form-grid" id="instrumentCreateForm">
            <h3>Add Instrument</h3>
            <input id="instrumentIdInput" type="text" autocomplete="off" placeholder="Instrument ID">
            <input id="instrumentNameInput" type="text" autocomplete="off" placeholder="Name">
            <div class="form-row">
              <input id="instrumentMarketInput" type="text" autocomplete="off" placeholder="Market">
              <input id="instrumentExchangeInput" type="text" autocomplete="off" placeholder="Exchange">
            </div>
            <div class="form-row">
              <input id="instrumentAssetClassInput" type="text" autocomplete="off" placeholder="Asset class">
              <input id="instrumentQuoteCurrencyInput" type="text" autocomplete="off" placeholder="Quote currency">
            </div>
            <textarea id="instrumentMetadataInput" placeholder='{"industry":"bank"}'></textarea>
            <button class="primary" type="submit">Create Instrument</button>
          </form>
          <form class="form-grid" id="instrumentTagMemberForm">
            <h3>Add Selected To List</h3>
            <select id="instrumentTagMemberSelect"></select>
            <button type="submit">Add To List</button>
          </form>
          <div class="error" id="instrumentError"></div>
        </div>
      </aside>
    </section>
  </section>
  <dialog id="tagCreateDialog" class="modal-dialog" aria-labelledby="tagCreateDialogTitle">
    <form class="modal-card" id="tagCreateForm">
      <div class="modal-header">
        <h2 id="tagCreateDialogTitle">New List</h2>
        <button id="closeTagDialogButton" type="button">Close</button>
      </div>
      <div class="modal-body">
        <input id="tagNameInput" type="text" autocomplete="off" placeholder="Name">
        <input id="tagColorInput" type="text" autocomplete="off" placeholder="#1d5fd1">
      </div>
      <div class="modal-actions">
        <button id="cancelTagDialogButton" type="button">Cancel</button>
        <button class="primary" type="submit">Create List</button>
      </div>
    </form>
  </dialog>
  <script>
    const payload = JSON.parse(document.getElementById("instrument-manager-payload").textContent);
    let instrumentSearchTimer = null;
    let instrumentState = {
      sources: [],
      instruments: [],
      total: 0,
      allTotal: null,
      tags: [],
      selectedSourceId: "",
      selectedTagId: "",
      selectedInstrumentId: "",
      query: "",
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

    function instrumentRequestOptions() {
      const options = { cache: "no-store" };
      if (payload.data_api_token) {
        const headers = new Headers();
        headers.set("Authorization", `Bearer ${payload.data_api_token}`);
        options.headers = headers;
      }
      return options;
    }

    function instrumentMutationOptions(method, body) {
      const options = instrumentRequestOptions();
      options.method = method;
      const headers = new Headers(options.headers || undefined);
      headers.set("Content-Type", "application/json");
      options.headers = headers;
      options.body = JSON.stringify(body);
      return options;
    }

    function instrumentApiUrl({ includeTag = true, limit = 200 } = {}) {
      const params = new URLSearchParams();
      params.set("limit", String(limit));
      if (instrumentState.selectedSourceId) params.set("source_id", instrumentState.selectedSourceId);
      if (includeTag && instrumentState.selectedTagId) params.set("tag", instrumentState.selectedTagId);
      if (instrumentState.query) params.set("q", instrumentState.query);
      return dataApiUrl(`/api/instruments?${params.toString()}`);
    }

    function sourceLabel(source) {
      return source.source_label || source.source_id || "Source";
    }

    function selectedInstrument() {
      return instrumentState.instruments.find((instrument) => instrument.instrument_id === instrumentState.selectedInstrumentId)
        || instrumentState.instruments[0]
        || null;
    }

    function renderFilters() {
      const sourceFilter = document.getElementById("instrumentSourceFilter");
      sourceFilter.innerHTML = `<option value="">All sources</option>${instrumentState.sources.map((source) => {
        const selected = source.source_id === instrumentState.selectedSourceId ? " selected" : "";
        return `<option value="${escapeHtml(source.source_id)}"${selected}>${escapeHtml(sourceLabel(source))}</option>`;
      }).join("")}`;

      const tagFilter = document.getElementById("instrumentTagFilter");
      tagFilter.innerHTML = `<option value="">All lists</option>${instrumentState.tags.map((tag) => {
        const selected = tag.tag_id === instrumentState.selectedTagId ? " selected" : "";
        return `<option value="${escapeHtml(tag.tag_id)}"${selected}>${escapeHtml(tag.name)}</option>`;
      }).join("")}`;

      const memberSelect = document.getElementById("instrumentTagMemberSelect");
      memberSelect.innerHTML = instrumentState.tags.map((tag) => (
        `<option value="${escapeHtml(tag.tag_id)}">${escapeHtml(tag.name)}</option>`
      )).join("");
    }

    function renderTags() {
      const list = document.getElementById("instrumentTagList");
      document.getElementById("tagMeta").textContent = `${instrumentState.tags.length} lists`;
      const allActive = instrumentState.selectedTagId ? "" : " active";
      const allItem = `<button class="tag-item${allActive}" data-special-tag="all" data-tag-id="" type="button">
        <span>All</span>
        <span class="tag-count">${escapeHtml(instrumentState.allTotal ?? instrumentState.total ?? 0)}</span>
      </button>`;
      const tagItems = instrumentState.tags.map((tag) => {
        const active = tag.tag_id === instrumentState.selectedTagId ? " active" : "";
        return `<button class="tag-item${active}" data-tag-id="${escapeHtml(tag.tag_id)}" type="button">
          <span>${escapeHtml(tag.name)}</span>
          <span class="tag-count">${escapeHtml(tag.member_count || 0)}</span>
        </button>`;
      }).join("");
      list.innerHTML = `${allItem}${tagItems}`;
      for (const button of list.querySelectorAll("[data-tag-id]")) {
        button.addEventListener("click", () => {
          instrumentState.selectedTagId = button.dataset.tagId || "";
          loadInstrumentManager();
        });
      }
    }

    function renderRows() {
      const rows = document.getElementById("instrumentRows");
      rows.innerHTML = instrumentState.instruments.length ? instrumentState.instruments.map((instrument) => {
        const selected = selectedInstrument()?.instrument_id === instrument.instrument_id ? " selected" : "";
        const tags = Array.isArray(instrument.tags) ? instrument.tags : [];
        return `<tr class="${selected}" data-instrument-id="${escapeHtml(instrument.instrument_id)}">
          <td><strong>${escapeHtml(instrument.instrument_id)}</strong></td>
          <td>${escapeHtml(instrument.name || "")}</td>
          <td>${escapeHtml(instrument.source_id || "")}</td>
          <td>${escapeHtml(instrument.market || instrument.asset_class || "")}</td>
          <td>${tags.map((tag) => `<span class="tag-chip">${escapeHtml(tag.name)}</span>`).join("")}</td>
        </tr>`;
      }).join("") : `<tr><td class="empty" colspan="5">No instruments</td></tr>`;
      for (const row of rows.querySelectorAll("[data-instrument-id]")) {
        row.addEventListener("click", () => {
          instrumentState.selectedInstrumentId = row.dataset.instrumentId || "";
          renderInstrumentManager();
        });
      }
    }

    function renderDetail() {
      const instrument = selectedInstrument();
      const detail = document.getElementById("instrumentDetail");
      const meta = document.getElementById("instrumentDetailMeta");
      if (!instrument) {
        meta.textContent = "No selection";
        detail.innerHTML = `<div class="empty">Select an instrument</div>`;
        return;
      }
      instrumentState.selectedInstrumentId = instrument.instrument_id;
      meta.textContent = instrument.instrument_id;
      const tags = Array.isArray(instrument.tags) ? instrument.tags : [];
      detail.innerHTML = `
        <div class="detail-row"><span>Name</span><strong>${escapeHtml(instrument.name || "")}</strong></div>
        <div class="detail-row"><span>Symbol</span><strong>${escapeHtml(instrument.symbol || "")}</strong></div>
        <div class="detail-row"><span>Source</span><strong>${escapeHtml(instrument.source_id || "")}</strong></div>
        <div class="detail-row"><span>Exchange</span><strong>${escapeHtml(instrument.exchange || "")}</strong></div>
        <div class="detail-row"><span>Market</span><strong>${escapeHtml(instrument.market || "")}</strong></div>
        <div class="detail-row"><span>Asset</span><strong>${escapeHtml(instrument.asset_class || "")}</strong></div>
        <div class="detail-row"><span>Lists</span><div>${tags.length ? tags.map((tag) => `<span class="tag-chip">${escapeHtml(tag.name)} <button data-remove-tag-id="${escapeHtml(tag.tag_id)}" type="button">x</button></span>`).join("") : "None"}</div></div>
      `;
      for (const button of detail.querySelectorAll("[data-remove-tag-id]")) {
        button.addEventListener("click", () => removeInstrumentFromTag(button.dataset.removeTagId || "", instrument.instrument_id));
      }
    }

    function renderInstrumentManager() {
      document.getElementById("instrumentError").textContent = instrumentState.error || "";
      renderFilters();
      renderTags();
      renderRows();
      renderDetail();
    }

    async function loadInstrumentManager() {
      if (!payload.data_api_base_url) {
        instrumentState.error = "Data API is not configured";
        renderInstrumentManager();
        return;
      }
      try {
        const sourcesResponse = await fetch(dataApiUrl("/api/data-sources"), instrumentRequestOptions());
        const tagsResponse = await fetch(dataApiUrl("/api/instrument-tags"), instrumentRequestOptions());
        const instrumentsResponse = await fetch(instrumentApiUrl(), instrumentRequestOptions());
        if (!sourcesResponse.ok || !tagsResponse.ok || !instrumentsResponse.ok) {
          throw new Error("Unable to load instruments");
        }
        const sourcesPayload = await sourcesResponse.json();
        const tagsPayload = await tagsResponse.json();
        const instrumentsPayload = await instrumentsResponse.json();
        let allTotal = Number(instrumentsPayload.total || 0);
        if (instrumentState.selectedTagId) {
          const allInstrumentsResponse = await fetch(instrumentApiUrl({ includeTag: false, limit: 1 }), instrumentRequestOptions());
          if (allInstrumentsResponse.ok) {
            const allInstrumentsPayload = await allInstrumentsResponse.json();
            allTotal = Number(allInstrumentsPayload.total || 0);
          }
        }
        instrumentState = {
          ...instrumentState,
          sources: Array.isArray(sourcesPayload.sources) ? sourcesPayload.sources : [],
          tags: Array.isArray(tagsPayload.tags) ? tagsPayload.tags : [],
          instruments: Array.isArray(instrumentsPayload.instruments) ? instrumentsPayload.instruments : [],
          total: Number(instrumentsPayload.total || 0),
          allTotal,
          error: "",
        };
      } catch (error) {
        instrumentState = { ...instrumentState, error: error.message };
      }
      renderInstrumentManager();
    }

    function createInstrumentPayload() {
      let metadata = {};
      const metadataText = document.getElementById("instrumentMetadataInput").value.trim();
      if (metadataText) {
        metadata = JSON.parse(metadataText);
      }
      const sourceId = instrumentState.selectedSourceId
        || (instrumentState.sources[0] ? instrumentState.sources[0].source_id : "");
      return {
        instrument_id: document.getElementById("instrumentIdInput").value,
        symbol: document.getElementById("instrumentIdInput").value,
        name: document.getElementById("instrumentNameInput").value,
        market: document.getElementById("instrumentMarketInput").value,
        exchange: document.getElementById("instrumentExchangeInput").value,
        asset_class: document.getElementById("instrumentAssetClassInput").value,
        quote_currency: document.getElementById("instrumentQuoteCurrencyInput").value,
        source_id: sourceId || undefined,
        metadata,
      };
    }

    async function createInstrument(event) {
      event.preventDefault();
      try {
        const payload = createInstrumentPayload();
        const response = await fetch(dataApiUrl("/api/instruments"), instrumentMutationOptions("POST", payload));
        if (!response.ok) throw new Error(await response.text());
        document.getElementById("instrumentCreateForm").reset();
        await loadInstrumentManager();
      } catch (error) {
        instrumentState.error = error.message;
        renderInstrumentManager();
      }
    }

    function openTagDialog() {
      const dialog = document.getElementById("tagCreateDialog");
      if (dialog.showModal) {
        dialog.showModal();
      } else {
        dialog.setAttribute("open", "");
      }
      document.getElementById("tagNameInput").focus();
    }

    function closeTagDialog() {
      document.getElementById("tagCreateForm").reset();
      const dialog = document.getElementById("tagCreateDialog");
      if (dialog.close) {
        dialog.close();
      } else {
        dialog.removeAttribute("open");
      }
    }

    async function createTag(event) {
      event.preventDefault();
      try {
        const payload = {
          name: document.getElementById("tagNameInput").value,
          color: document.getElementById("tagColorInput").value || undefined,
        };
        const response = await fetch(dataApiUrl("/api/instrument-tags"), instrumentMutationOptions("POST", payload));
        if (!response.ok) throw new Error(await response.text());
        closeTagDialog();
        await loadInstrumentManager();
      } catch (error) {
        instrumentState.error = error.message;
        renderInstrumentManager();
      }
    }

    async function addInstrumentToTag(tagId, instrumentId) {
      if (!tagId || !instrumentId) return;
      const payload = { instrument_ids: [instrumentId] };
      const response = await fetch(dataApiUrl(`/api/instrument-tags/${encodeURIComponent(tagId)}/members`), instrumentMutationOptions("POST", payload));
      if (!response.ok) throw new Error(await response.text());
      await loadInstrumentManager();
    }

    async function removeInstrumentFromTag(tagId, instrumentId) {
      if (!tagId || !instrumentId) return;
      const response = await fetch(
        dataApiUrl(`/api/instrument-tags/${encodeURIComponent(tagId)}/members/${encodeURIComponent(instrumentId)}`),
        instrumentMutationOptions("DELETE", {}),
      );
      if (!response.ok) {
        instrumentState.error = await response.text();
      }
      await loadInstrumentManager();
    }

    document.getElementById("instrumentRefreshButton").addEventListener("click", loadInstrumentManager);
    document.getElementById("openTagDialogButton").addEventListener("click", openTagDialog);
    document.getElementById("closeTagDialogButton").addEventListener("click", closeTagDialog);
    document.getElementById("cancelTagDialogButton").addEventListener("click", closeTagDialog);
    document.getElementById("tagCreateDialog").addEventListener("click", (event) => {
      if (event.target === event.currentTarget) closeTagDialog();
    });
    document.getElementById("tagCreateDialog").addEventListener("cancel", () => {
      document.getElementById("tagCreateForm").reset();
    });
    document.getElementById("instrumentSourceFilter").addEventListener("change", (event) => {
      instrumentState.selectedSourceId = event.target.value;
      loadInstrumentManager();
    });
    document.getElementById("instrumentTagFilter").addEventListener("change", (event) => {
      instrumentState.selectedTagId = event.target.value;
      loadInstrumentManager();
    });
    document.getElementById("instrumentSearchInput").addEventListener("input", (event) => {
      clearTimeout(instrumentSearchTimer);
      instrumentSearchTimer = setTimeout(() => {
        instrumentState.query = event.target.value.trim();
        loadInstrumentManager();
      }, 250);
    });
    document.getElementById("instrumentCreateForm").addEventListener("submit", createInstrument);
    document.getElementById("tagCreateForm").addEventListener("submit", createTag);
    document.getElementById("instrumentTagMemberForm").addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await addInstrumentToTag(
          document.getElementById("instrumentTagMemberSelect").value,
          selectedInstrument()?.instrument_id || "",
        );
      } catch (error) {
        instrumentState.error = error.message;
        renderInstrumentManager();
      }
    });
    document.getElementById("deleteInstrumentButton").addEventListener("click", async () => {
      const instrument = selectedInstrument();
      if (!instrument || !window.confirm(`Delete ${instrument.instrument_id}?`)) return;
      const response = await fetch(
        dataApiUrl(`/api/instruments/${encodeURIComponent(instrument.instrument_id)}`),
        instrumentMutationOptions("DELETE", {}),
      );
      if (!response.ok) {
        instrumentState.error = await response.text();
      }
      instrumentState.selectedInstrumentId = "";
      await loadInstrumentManager();
    });

    loadInstrumentManager();
  </script>
</body>
</html>
""".replace("__INSTRUMENT_MANAGER_PAYLOAD__", safe_payload)


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
    .text-button.danger-button {
      border-color: #f1b8ad;
      background: #fff7f5;
      color: var(--red);
    }
    .text-button.danger-button:hover {
      border-color: #df8b7d;
      background: #fff0ed;
    }
    .text-button.success-button {
      border-color: #b7dfc7;
      background: #eef8f3;
      color: var(--green);
    }
    .text-button.success-button:hover {
      border-color: #8bcaa5;
      background: #e4f4eb;
    }
    .drawer-backdrop {
      position: fixed;
      inset: 0;
      z-index: 19;
      background: rgb(21 31 43 / 24%);
    }
    .drawer-backdrop[hidden] { display: none; }
    .data-drawer {
      position: fixed;
      top: 16px;
      left: 50%;
      z-index: 20;
      width: min(1180px, calc(100vw - 32px));
      height: min(76vh, 760px);
      display: grid;
      grid-template-rows: auto auto minmax(0, 1fr);
      transform: translateX(-50%);
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 24px 60px rgb(21 31 43 / 24%);
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
    .drawer-main-tabs {
      display: flex;
      gap: 8px;
      padding: 10px 16px;
      border-bottom: 1px solid var(--line);
      background: #fff;
    }
    .drawer-main-tab {
      min-height: 32px;
      padding: 0 12px;
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
    .drawer-main-tab.active {
      border-color: #b7d4ff;
      background: #eef5ff;
      color: #195bb8;
    }
    .drawer-panel {
      min-height: 0;
      overflow: hidden;
    }
    .drawer-panel[hidden] { display: none; }
    .schedule-drawer-panel {
      display: grid;
      grid-template-rows: minmax(220px, 1fr) minmax(170px, 0.85fr);
      gap: 12px;
      padding: 12px 16px;
    }
    .task-drawer-panel {
      display: grid;
      grid-template-rows: auto auto auto minmax(0, 1fr) auto;
      min-height: 0;
    }
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
      grid-template-rows: auto minmax(0, 1fr) auto;
      gap: 8px;
      max-height: 220px;
      overflow: auto;
      padding: 10px 16px 12px;
      border-bottom: 1px solid var(--line);
    }
    .schedule-runs-panel { max-height: 180px; }
    .schedule-drawer-panel .schedule-panel {
      max-height: none;
      min-height: 0;
      overflow: hidden;
      padding: 10px;
      border: 1px solid var(--line-soft);
      border-radius: 6px;
    }
    .schedule-drawer-panel .schedule-runs-panel { max-height: none; }
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
      min-height: 0;
      overflow: auto;
      border: 1px solid var(--line-soft);
      border-radius: 6px;
    }
    .panel-pagination {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      min-height: 32px;
      color: var(--muted);
      font-size: 12px;
    }
    .panel-pagination-controls {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .panel-page-size {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 800;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .panel-page-size select {
      min-height: 28px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      font: inherit;
      font-size: 12px;
      font-weight: 700;
      text-transform: none;
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
      width: min(860px, 94vw);
      max-height: 90vh;
      overflow: auto;
      transform: translateX(-50%);
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: 0 24px 60px rgb(21 31 43 / 28%);
    }
    .schedule-editor[hidden] { display: none; }
    .schedule-editor [hidden] { display: none !important; }
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
    .schedule-editor-summary {
      padding: 10px 12px;
      border: 1px solid #cfe0f8;
      border-radius: 6px;
      background: #f5f9ff;
      color: #30506f;
      font-size: 12px;
      line-height: 1.45;
    }
    .schedule-editor-section {
      display: grid;
      gap: 10px;
      padding-top: 2px;
    }
    .schedule-editor-section h4 {
      margin: 0;
      color: var(--text);
      font-size: 13px;
    }
    .schedule-editor-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
      gap: 10px;
    }
    .schedule-editor-grid.compact {
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
    }
    .schedule-editor-grid.trigger-grid {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: end;
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
      box-sizing: border-box;
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
    .schedule-editor-field.number-field {
      flex: 0 0 76px;
    }
    .schedule-editor-field.unit-field {
      flex: 0 0 140px;
    }
    .schedule-editor-field.datetime-field {
      flex: 1 1 280px;
      min-width: 260px;
    }
    .schedule-editor-field.delay-field {
      flex: 0 0 120px;
    }
    .schedule-editor-field.delay-unit-field {
      flex-basis: 130px;
    }
    @media (max-width: 720px) {
      .schedule-editor-field.datetime-field {
        flex-basis: 100%;
      }
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
    .schedule-editor-segmented,
    .weekday-pills {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }
    .schedule-editor-segmented button,
    .weekday-pill {
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
    .schedule-editor-segmented button.active,
    .weekday-pill:has(input:checked) {
      border-color: #b7d4ff;
      background: #eef5ff;
      color: #195bb8;
    }
    .weekday-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .weekday-pill input { margin: 0; }
    .frequency-multiselect {
      position: relative;
      min-width: 0;
    }
    .frequency-toggle {
      box-sizing: border-box;
      min-height: 32px;
      width: 100%;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 0 9px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      font: inherit;
      font-size: 12px;
      font-weight: 800;
      cursor: pointer;
      text-align: left;
    }
    .frequency-toggle:hover {
      border-color: #b8c7d6;
      background: #f8fafc;
    }
    .frequency-toggle-caret {
      color: var(--muted);
      font-size: 12px;
    }
    .frequency-menu {
      position: absolute;
      top: calc(100% + 4px);
      left: 0;
      z-index: 35;
      min-width: 180px;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      box-shadow: 0 12px 28px rgb(21 31 43 / 18%);
    }
    .frequency-menu[hidden] { display: none; }
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
    .task-table-wrap {
      min-height: 0;
      overflow: auto;
    }
    .task-table-wrap th:last-child,
    .task-table-wrap td:last-child {
      text-align: left;
      white-space: normal;
      min-width: 240px;
      max-width: 460px;
    }
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
      .data-drawer {
        top: 8px;
        width: calc(100vw - 16px);
        height: calc(100vh - 16px);
      }
      .schedule-drawer-panel { grid-template-rows: minmax(180px, 1fr) minmax(150px, 0.8fr); }
      .drawer-filters { grid-template-columns: 1fr; }
      .panel-pagination { align-items: flex-start; flex-direction: column; }
      .panel-pagination-controls { flex-wrap: wrap; }
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
    <div class="drawer-main-tabs" role="tablist" aria-label="Data source monitor sections">
      <button class="drawer-main-tab active" id="scheduleDrawerTab" data-drawer-tab="schedules" type="button" role="tab" aria-selected="true" aria-controls="scheduleDrawerPanel">Schedules</button>
      <button class="drawer-main-tab" id="taskDrawerTab" data-drawer-tab="tasks" type="button" role="tab" aria-selected="false" aria-controls="taskDrawerPanel">Crawl Tasks</button>
    </div>
    <div class="drawer-panel schedule-drawer-panel" id="scheduleDrawerPanel" role="tabpanel" aria-labelledby="scheduleDrawerTab">
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
                <th>Range</th>
                <th>Next Run</th>
                <th>Last Job</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody id="dataScheduleRows"></tbody>
          </table>
        </div>
        <div class="panel-pagination">
          <span id="schedulePaginationMeta"></span>
          <div class="panel-pagination-controls">
            <label class="panel-page-size">
              Page Size
              <select id="schedulePageSizeSelect">
                <option value="10">10</option>
                <option value="25" selected>25</option>
                <option value="50">50</option>
                <option value="100">100</option>
              </select>
            </label>
            <button class="text-button" id="schedulePreviousPageButton" type="button">Previous</button>
            <button class="text-button" id="scheduleNextPageButton" type="button">Next</button>
          </div>
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
                <th>Range</th>
                <th>Run Status</th>
                <th>Job Status</th>
                <th>Triggered</th>
                <th>Job</th>
              </tr>
            </thead>
            <tbody id="dataScheduleRunRows"></tbody>
          </table>
        </div>
        <div class="panel-pagination">
          <span id="scheduleRunPaginationMeta"></span>
          <div class="panel-pagination-controls">
            <label class="panel-page-size">
              Page Size
              <select id="scheduleRunPageSizeSelect">
                <option value="10">10</option>
                <option value="25" selected>25</option>
                <option value="50">50</option>
                <option value="100">100</option>
              </select>
            </label>
            <button class="text-button" id="scheduleRunPreviousPageButton" type="button">Previous</button>
            <button class="text-button" id="scheduleRunNextPageButton" type="button">Next</button>
          </div>
        </div>
      </section>
    </div>
    <div class="drawer-panel task-drawer-panel" id="taskDrawerPanel" role="tabpanel" aria-labelledby="taskDrawerTab" hidden>
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
              <th>Range</th>
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
      <div class="schedule-editor-summary" id="scheduleEditSummary"></div>
      <section class="schedule-editor-section">
        <h4>Basic</h4>
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
            <span>Timezone</span>
            <input id="scheduleEditTimezone" type="text" autocomplete="off">
          </label>
          <label class="schedule-editor-field">
            <span>Overlap</span>
            <select id="scheduleEditOverlapPolicy">
              <option value="skip">Skip running jobs</option>
              <option value="allow">Allow overlap</option>
            </select>
          </label>
        </div>
      </section>
      <section class="schedule-editor-section">
        <h4>Trigger</h4>
        <select id="scheduleEditTriggerType" hidden>
          <option value="interval">interval</option>
          <option value="daily">daily</option>
          <option value="weekly">weekly</option>
          <option value="once">once</option>
        </select>
        <div class="schedule-editor-segmented" id="scheduleEditTriggerTabs">
          <button data-schedule-trigger="interval" type="button">Interval</button>
          <button data-schedule-trigger="daily" type="button">Daily</button>
          <button data-schedule-trigger="weekly" type="button">Weekly</button>
          <button data-schedule-trigger="once" type="button">Once</button>
        </div>
        <div class="schedule-editor-grid trigger-grid">
          <label class="schedule-editor-field number-field" data-trigger-field="interval">
            <span>Every</span>
            <input id="scheduleEditEvery" type="number" min="1" step="1">
          </label>
          <label class="schedule-editor-field unit-field" data-trigger-field="interval">
            <span>Unit</span>
            <select id="scheduleEditUnit">
              <option value="seconds">seconds</option>
              <option value="minutes">minutes</option>
              <option value="hours">hours</option>
              <option value="days">days</option>
            </select>
          </label>
          <input id="scheduleEditTime" type="hidden">
          <label class="schedule-editor-field datetime-field" data-trigger-field="interval daily weekly">
            <span>Start At</span>
            <input id="scheduleEditStartAt" type="datetime-local" step="1">
          </label>
          <label class="schedule-editor-field datetime-field" data-trigger-field="once">
            <span>Run At</span>
            <input id="scheduleEditRunAt" type="datetime-local" step="1">
          </label>
          <label class="schedule-editor-field delay-field">
            <span>Execution delay</span>
            <input id="scheduleEditExecutionDelayValue" type="number" min="0" step="1">
          </label>
          <label class="schedule-editor-field unit-field delay-unit-field">
            <span>Delay Unit</span>
            <select id="scheduleEditExecutionDelayUnit">
              <option value="seconds">seconds</option>
              <option value="minutes">minutes</option>
              <option value="hours">hours</option>
            </select>
          </label>
        </div>
        <input id="scheduleEditDaysOfWeek" type="hidden">
        <div class="weekday-pills" id="scheduleEditDaysOfWeekPills" data-trigger-field="weekly">
          <label class="weekday-pill"><input type="checkbox" value="mon">Mon</label>
          <label class="weekday-pill"><input type="checkbox" value="tue">Tue</label>
          <label class="weekday-pill"><input type="checkbox" value="wed">Wed</label>
          <label class="weekday-pill"><input type="checkbox" value="thu">Thu</label>
          <label class="weekday-pill"><input type="checkbox" value="fri">Fri</label>
          <label class="weekday-pill"><input type="checkbox" value="sat">Sat</label>
          <label class="weekday-pill"><input type="checkbox" value="sun">Sun</label>
        </div>
      </section>
      <section class="schedule-editor-section">
        <h4>Repeat</h4>
        <div class="schedule-editor-grid compact">
          <label class="schedule-editor-field">
            <span>Mode</span>
            <select id="scheduleEditRepeatMode">
              <option value="forever">Forever</option>
              <option value="count">Run count</option>
              <option value="until">Until time</option>
            </select>
          </label>
          <label class="schedule-editor-field" data-repeat-field="count">
            <span>Count</span>
            <input id="scheduleEditRepeatCount" type="number" min="1" step="1">
          </label>
          <label class="schedule-editor-field" data-repeat-field="until">
            <span>Until</span>
            <input id="scheduleEditUntil" type="datetime-local" step="1">
          </label>
        </div>
      </section>
      <section class="schedule-editor-section">
        <h4>Data</h4>
        <div class="schedule-editor-grid">
          <label class="schedule-editor-field">
            <span>Symbols</span>
            <input id="scheduleEditSymbols" type="text" autocomplete="off">
          </label>
          <div class="schedule-editor-field">
            <span>Frequencies</span>
            <input id="scheduleEditFrequencies" type="hidden">
            <div class="frequency-multiselect" id="scheduleEditFrequencyDropdown">
              <button class="frequency-toggle" id="scheduleEditFrequencyToggle" type="button" aria-expanded="false" aria-controls="scheduleEditFrequencyMenu">
                <span id="scheduleEditFrequencySummary">Select frequencies</span>
                <span class="frequency-toggle-caret">▾</span>
              </button>
              <div class="frequency-menu" id="scheduleEditFrequencyMenu" hidden>
                <div class="weekday-pills" id="scheduleEditFrequencyPills">
                  <label class="weekday-pill"><input type="checkbox" value="1d">1d</label>
                  <label class="weekday-pill"><input type="checkbox" value="4h">4h</label>
                  <label class="weekday-pill"><input type="checkbox" value="1h">1h</label>
                  <label class="weekday-pill"><input type="checkbox" value="15m">15m</label>
                  <label class="weekday-pill"><input type="checkbox" value="1m">1m</label>
                </div>
              </div>
            </div>
          </div>
          <label class="schedule-editor-field">
            <span>Range</span>
            <select id="scheduleEditRangePreset">
              <option value="last_n_minutes">Last N mins</option>
              <option value="last_n_hours">Last N hours</option>
              <option value="last_n_days">Last N days</option>
              <option value="fixed">Fixed time range</option>
            </select>
          </label>
          <select id="scheduleEditDateRangeType" hidden>
            <option value="last_n_days">last_n_days</option>
            <option value="fixed">fixed</option>
          </select>
          <label class="schedule-editor-field" data-range-field="last_n_days">
            <span>N</span>
            <input id="scheduleEditRangeValue" type="number" min="1" step="1">
          </label>
          <label class="schedule-editor-field" data-range-field="fixed">
            <span>Start At</span>
            <input id="scheduleEditRangeStartAt" type="datetime-local" step="60">
          </label>
          <label class="schedule-editor-field" data-range-field="fixed">
            <span>End At</span>
            <input id="scheduleEditRangeEndAt" type="datetime-local" step="60">
          </label>
          <label class="schedule-editor-field checkbox-field">
            <input id="scheduleEditRefreshExisting" type="checkbox">
            <span>Refresh existing coverage</span>
          </label>
        </div>
      </section>
      <section class="schedule-editor-section">
        <h4>Runtime</h4>
        <div class="schedule-editor-grid compact">
          <label class="schedule-editor-field">
            <span>Request gap seconds</span>
            <input id="scheduleEditPageDelaySeconds" type="number" min="0" step="0.05">
          </label>
        </div>
      </section>
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
    <a href="/instruments">
      <strong>Instrument Lists</strong>
      <span>Browse instruments, tags, and watchlist-style lists from the data API.</span>
    </a>
  </main>
  <script>
    const payload = JSON.parse(document.getElementById("workbench-index-payload").textContent);
    const DATA_MONITOR_REFRESH_MS = 10000;
    const WORKBENCH_DISPLAY_TIME_ZONE = "Asia/Shanghai";
    const WORKBENCH_DISPLAY_TIME_ZONE_OFFSET = "+08:00";
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
      activeDrawerTab: "schedules",
      schedulePage: 1,
      schedulePageSize: 25,
      scheduleRunPage: 1,
      scheduleRunPageSize: 25,
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

    function hasExplicitTimeZone(value) {
      return /(?:Z|[+-]\\d{2}:?\\d{2})$/i.test(String(value).trim());
    }

    function parseWorkbenchDateTime(value) {
      if (!value) return "";
      if (value instanceof Date) {
        return Number.isNaN(value.getTime()) ? null : value;
      }
      const text = String(value).trim();
      const dateOnly = text.match(/^(\\d{4}-\\d{2}-\\d{2})$/);
      if (dateOnly) {
        return new Date(`${dateOnly[1]}T00:00:00${WORKBENCH_DISPLAY_TIME_ZONE_OFFSET}`);
      }
      const dateTime = text.match(/^(\\d{4}-\\d{2}-\\d{2})[T ](\\d{2}:\\d{2}(?::\\d{2}(?:\\.\\d+)?)?)(.*)$/);
      if (dateTime && !hasExplicitTimeZone(text)) {
        return new Date(`${dateTime[1]}T${dateTime[2]}${WORKBENCH_DISPLAY_TIME_ZONE_OFFSET}`);
      }
      const parsed = new Date(text);
      return Number.isNaN(parsed.getTime()) ? null : parsed;
    }

    function displayDateTimeParts(value) {
      const date = parseWorkbenchDateTime(value);
      if (!date) return null;
      const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: WORKBENCH_DISPLAY_TIME_ZONE,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hourCycle: "h23",
      }).formatToParts(date);
      return Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
    }

    function datePartsInDisplayZone(value) {
      if (!value) return null;
      const text = String(value);
      const dateOnly = text.match(/^(\\d{4})-(\\d{2})-(\\d{2})$/);
      if (dateOnly) {
        return { year: dateOnly[1], month: dateOnly[2], day: dateOnly[3] };
      }
      const parts = displayDateTimeParts(value);
      return parts ? { year: parts.year, month: parts.month, day: parts.day } : null;
    }

    function formatClock(value) {
      if (!value) return "";
      const date = parseWorkbenchDateTime(value);
      if (!date) return String(value);
      return date.toLocaleTimeString([], {
        timeZone: WORKBENCH_DISPLAY_TIME_ZONE,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    }

    function sourceLabel(source) {
      return source.source_label || source.source_id || "Source";
    }

    function formatDateTime(value) {
      if (!value) return "";
      const date = parseWorkbenchDateTime(value);
      if (!date) return String(value);
      return date.toLocaleString([], {
        timeZone: WORKBENCH_DISPLAY_TIME_ZONE,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    }

    function padDatePart(value) {
      return String(value).padStart(2, "0");
    }

    function isoDate(date) {
      return `${date.getFullYear()}-${padDatePart(date.getMonth() + 1)}-${padDatePart(date.getDate())}`;
    }

    function localDate(value) {
      if (!value) return null;
      const parts = datePartsInDisplayZone(value);
      if (!parts) return null;
      return new Date(Number(parts.year), Number(parts.month) - 1, Number(parts.day));
    }

    function addDays(date, days) {
      const result = new Date(date.getTime());
      result.setDate(result.getDate() + days);
      return result;
    }

    function addRangeTime(date, amount, unit) {
      if (unit === "minutes") {
        return new Date(date.getTime() + amount * 60 * 1000);
      }
      if (unit === "hours") {
        return new Date(date.getTime() + amount * 60 * 60 * 1000);
      }
      return new Date(date.getTime() + amount * 24 * 60 * 60 * 1000);
    }

    function safeRangeUnit(unit) {
      return ["minutes", "hours", "days"].includes(unit) ? unit : "days";
    }

    function rangePresetUnit(preset) {
      if (preset === "last_n_minutes") return "minutes";
      if (preset === "last_n_hours") return "hours";
      return "days";
    }

    function rangePresetLabel(preset, value) {
      if (preset === "last_n_minutes") return `Last ${value} mins`;
      if (preset === "last_n_hours") return `Last ${value} hours`;
      if (preset === "last_n_days") return `Last ${value} days`;
      return "Fixed time range";
    }

    function rangePresetForDateRange(range) {
      if (range.type === "fixed") return "fixed";
      const unit = safeRangeUnit(range.lookback_unit || "days");
      if (unit === "minutes") return "last_n_minutes";
      if (unit === "hours") return "last_n_hours";
      return "last_n_days";
    }

    function delaySeconds(value, unit) {
      const amount = Math.max(0, Number(value) || 0);
      if (unit === "hours") return amount * 3600;
      if (unit === "minutes") return amount * 60;
      return amount;
    }

    function setDelayInputs(totalSeconds) {
      const seconds = Math.max(0, Number(totalSeconds) || 0);
      if (seconds > 0 && seconds % 3600 === 0) {
        setInputValue("scheduleEditExecutionDelayValue", seconds / 3600);
        setInputValue("scheduleEditExecutionDelayUnit", "hours");
      } else if (seconds > 0 && seconds % 60 === 0) {
        setInputValue("scheduleEditExecutionDelayValue", seconds / 60);
        setInputValue("scheduleEditExecutionDelayUnit", "minutes");
      } else {
        setInputValue("scheduleEditExecutionDelayValue", seconds);
        setInputValue("scheduleEditExecutionDelayUnit", "seconds");
      }
    }

    function formatDateOnly(value) {
      const date = localDate(value);
      return date ? isoDate(date) : "";
    }

    function formatDateRange(startValue, endValue) {
      const startDate = formatDateOnly(startValue);
      const endDate = formatDateOnly(endValue);
      if (startDate && endDate) return `${startDate} to ${endDate}`;
      return startDate || endDate || "";
    }

    function formatTaskRange(task) {
      return formatDateRange(task.start_date, task.end_date);
    }

    function formatScheduleDateRange(schedule, anchorValue) {
      const range = scheduleConfig(schedule).job?.date_range || {};
      if (range.type === "fixed") {
        if (range.start_at || range.end_at) {
          const startText = formatDateTime(range.start_at);
          const endText = formatDateTime(range.end_at);
          if (startText && endText) return `${startText} to ${endText}`;
          return startText || endText || "";
        }
        return formatDateRange(range.start_date, range.end_date);
      }
      if (range.type === "last_n_days") {
        const trigger = scheduleConfig(schedule).trigger || {};
        const delay = Math.max(0, Number(trigger.execution_delay_seconds) || 0);
        const anchor = anchorValue ? new Date(anchorValue) : new Date();
        const rangeAnchor = Number.isNaN(anchor.getTime())
          ? anchorValue
          : new Date(anchor.getTime() - delay * 1000);
        const lookbackValue = Math.max(1, Number(range.lookback_value ?? range.days) || 1);
        const lookbackUnit = safeRangeUnit(range.lookback_unit || "days");
        const endLagValue = Math.max(0, Number(range.end_offset_value ?? range.end_offset_days) || 0);
        const endLagUnit = safeRangeUnit(range.end_offset_unit || "days");
        if (lookbackUnit === "days" && endLagUnit === "days") {
          const anchorDate = localDate(rangeAnchor) || localDate(new Date());
          if (!anchorDate) return "";
          const endDate = addDays(anchorDate, -endLagValue);
          const startDate = addDays(endDate, -(lookbackValue - 1));
          return `${isoDate(startDate)} to ${isoDate(endDate)}`;
        }
        const anchorDateTime = rangeAnchor ? new Date(rangeAnchor) : new Date();
        if (Number.isNaN(anchorDateTime.getTime())) return "";
        const endAt = addRangeTime(anchorDateTime, -endLagValue, endLagUnit);
        const startAt = addRangeTime(endAt, -lookbackValue, lookbackUnit);
        return `${formatDateTime(startAt)} to ${formatDateTime(endAt)}`;
      }
      return "";
    }

    function defaultTaskFilters() {
      return { symbol: "", frequencies: [], statuses: [], page: 1, pageSize: 50 };
    }

    function clampPage(page, totalPages) {
      const safeTotalPages = Math.max(1, Number(totalPages) || 1);
      const safePage = Math.max(1, Number(page) || 1);
      return Math.min(safePage, safeTotalPages);
    }

    function paginatedItems(items, page, pageSize) {
      const safeItems = Array.isArray(items) ? items : [];
      const safePageSize = Math.max(1, Number(pageSize) || 25);
      const total = safeItems.length;
      const totalPages = Math.max(1, Math.ceil(total / safePageSize));
      const safePage = clampPage(page, totalPages);
      const startIndex = (safePage - 1) * safePageSize;
      const endIndex = Math.min(startIndex + safePageSize, total);
      return {
        items: safeItems.slice(startIndex, endIndex),
        page: safePage,
        pageSize: safePageSize,
        total,
        totalPages,
        start: total ? startIndex + 1 : 0,
        end: endIndex,
      };
    }

    function renderPanelPagination(pageInfo, ids) {
      const metaEl = document.getElementById(ids.metaId);
      const previousButton = document.getElementById(ids.previousId);
      const nextButton = document.getElementById(ids.nextId);
      const pageSizeSelect = document.getElementById(ids.pageSizeId);
      if (metaEl) {
        metaEl.textContent = pageInfo.total
          ? `Page ${pageInfo.page} / ${pageInfo.totalPages} · ${pageInfo.start}-${pageInfo.end} / ${pageInfo.total}`
          : "Page 1 / 1 · 0 total";
      }
      if (previousButton) previousButton.disabled = pageInfo.page <= 1;
      if (nextButton) nextButton.disabled = pageInfo.page >= pageInfo.totalPages;
      if (pageSizeSelect && pageSizeSelect.value !== String(pageInfo.pageSize)) {
        pageSizeSelect.value = String(pageInfo.pageSize);
      }
    }

    function renderSchedulePagination(pageInfo) {
      renderPanelPagination(pageInfo, {
        metaId: "schedulePaginationMeta",
        previousId: "schedulePreviousPageButton",
        nextId: "scheduleNextPageButton",
        pageSizeId: "schedulePageSizeSelect",
      });
    }

    function renderScheduleRunPagination(pageInfo) {
      renderPanelPagination(pageInfo, {
        metaId: "scheduleRunPaginationMeta",
        previousId: "scheduleRunPreviousPageButton",
        nextId: "scheduleRunNextPageButton",
        pageSizeId: "scheduleRunPageSizeSelect",
      });
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

    function activeDrawerTab() {
      return dataMonitorState.activeDrawerTab === "tasks" ? "tasks" : "schedules";
    }

    function syncDrawerTabs() {
      const activeTab = activeDrawerTab();
      for (const button of document.querySelectorAll("[data-drawer-tab]")) {
        const isActive = button.dataset.drawerTab === activeTab;
        button.classList.toggle("active", isActive);
        button.setAttribute("aria-selected", String(isActive));
        const panelId = button.getAttribute("aria-controls");
        const panel = panelId ? document.getElementById(panelId) : null;
        if (panel) {
          panel.hidden = !isActive;
        }
      }
    }

    function setDrawerTab(tabId) {
      dataMonitorState.activeDrawerTab = tabId === "tasks" ? "tasks" : "schedules";
      syncDrawerTabs();
      renderTaskDrawer();
      const source = selectedSource();
      if (activeDrawerTab() === "tasks" && source && !dataMonitorState.taskPagesBySource[source.source_id]) {
        loadSelectedTaskPage();
      }
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
      const delaySeconds = Math.max(0, Number(trigger.execution_delay_seconds) || 0);
      if (delaySeconds > 0) {
        const delayText = delaySeconds % 3600 === 0
          ? `${delaySeconds / 3600}h delay`
          : delaySeconds % 60 === 0
            ? `${delaySeconds / 60}m delay`
            : `${delaySeconds}s delay`;
        label = `${label} · ${delayText}`;
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
        renderSchedulePagination(paginatedItems([], 1, dataMonitorState.schedulePageSize));
        rowsEl.innerHTML = `<tr><td class="empty" colspan="8">Unable to load schedules</td></tr>`;
        return;
      }
      const schedules = scheduleList();
      const counts = scheduleStatusCounts();
      const pageInfo = paginatedItems(schedules, dataMonitorState.schedulePage, dataMonitorState.schedulePageSize);
      dataMonitorState.schedulePage = pageInfo.page;
      dataMonitorState.schedulePageSize = pageInfo.pageSize;
      renderSchedulePagination(pageInfo);
      metaEl.textContent = `${counts.total} schedules · ${counts.active} active · ${counts.completed} completed`;
      rowsEl.innerHTML = schedules.length ? pageInfo.items.map((schedule) => {
        const status = escapeHtml(schedule.status || (schedule.enabled ? "enabled" : "disabled"));
        const lastJob = schedule.last_job_id || "";
        const lastRun = schedule.last_run_at ? `last run ${formatDateTime(schedule.last_run_at)}` : "";
        const scheduleId = escapeHtml(schedule.schedule_id || "");
        const toggleText = schedule.enabled ? "Disable" : "Enable";
        const toggleClass = schedule.enabled ? "danger-button" : "success-button";
        const rangeAnchor = schedule.next_run_at || schedule.last_run_at || new Date();
        const rangeText = formatScheduleDateRange(schedule, rangeAnchor);
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
          <td>${escapeHtml(rangeText)}</td>
          <td>${escapeHtml(formatDateTime(schedule.next_run_at))}</td>
          <td>
            <div class="schedule-name">
              <strong>${escapeHtml(lastJob)}</strong>
              <span class="schedule-subline">${escapeHtml(lastRun)}</span>
            </div>
          </td>
          <td>
            <div class="schedule-actions">
              <button class="text-button schedule-toggle-button ${toggleClass}" data-schedule-action="toggle" data-schedule-id="${scheduleId}" type="button">${toggleText}</button>
              <button class="text-button" data-schedule-action="run" data-schedule-id="${scheduleId}" type="button">Run</button>
              <button class="text-button" data-schedule-action="edit" data-schedule-id="${scheduleId}" type="button">Edit</button>
            </div>
          </td>
        </tr>`;
      }).join("") : `<tr><td class="empty" colspan="8">No schedules</td></tr>`;
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

    function toDatetimeLocalValue(value) {
      if (!value) return "";
      const parts = displayDateTimeParts(value);
      if (!parts) return "";
      return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`;
    }

    function dateToDatetimeLocalValue(value, endOfDay = false) {
      if (!value) return "";
      const text = String(value);
      if (!/^\\d{4}-\\d{2}-\\d{2}$/.test(text)) return "";
      return `${text}T${endOfDay ? "23:59" : "00:00"}`;
    }

    function setSelectedWeekdays(values) {
      const selected = new Set(Array.isArray(values) ? values : []);
      for (const input of document.querySelectorAll("#scheduleEditDaysOfWeekPills input")) {
        input.checked = selected.has(input.value);
      }
      setInputValue("scheduleEditDaysOfWeek", Array.from(selected).join(", "));
    }

    function selectedWeekdays() {
      return Array.from(document.querySelectorAll("#scheduleEditDaysOfWeekPills input:checked"))
        .map((input) => input.value);
    }

    function updateFrequencySummary() {
      const selected = Array.from(document.querySelectorAll("#scheduleEditFrequencyPills input:checked"))
        .map((input) => input.value);
      setInputValue("scheduleEditFrequencies", selected.join(", "));
      const summary = document.getElementById("scheduleEditFrequencySummary");
      if (summary) {
        summary.textContent = selected.length ? selected.join(", ") : "Select frequencies";
      }
    }

    function setSelectedFrequencies(values) {
      const selected = new Set(Array.isArray(values) ? values : []);
      for (const input of document.querySelectorAll("#scheduleEditFrequencyPills input")) {
        input.checked = selected.has(input.value);
      }
      updateFrequencySummary();
    }

    function selectedFrequencies() {
      return Array.from(document.querySelectorAll("#scheduleEditFrequencyPills input:checked"))
        .map((input) => input.value);
    }

    function closeFrequencyMenu() {
      const menu = document.getElementById("scheduleEditFrequencyMenu");
      const toggle = document.getElementById("scheduleEditFrequencyToggle");
      if (menu) {
        menu.hidden = true;
      }
      if (toggle) {
        toggle.setAttribute("aria-expanded", "false");
      }
    }

    function toggleFrequencyMenu() {
      const menu = document.getElementById("scheduleEditFrequencyMenu");
      const toggle = document.getElementById("scheduleEditFrequencyToggle");
      if (!menu || !toggle) return;
      const isOpening = menu.hidden;
      menu.hidden = !isOpening;
      toggle.setAttribute("aria-expanded", isOpening ? "true" : "false");
    }

    function setScheduleTriggerMode(triggerType) {
      setInputValue("scheduleEditTriggerType", triggerType || "interval");
      syncScheduleEditorControls();
    }

    function syncControlGroup(selector, activeValue, attrName) {
      for (const element of document.querySelectorAll(selector)) {
        const values = String(element.getAttribute(attrName) || "").split(/\\s+/).filter(Boolean);
        element.hidden = !values.includes(activeValue);
      }
    }

    function syncScheduleStartAt() {
      const triggerType = inputValue("scheduleEditTriggerType") || "interval";
      if (triggerType === "once") {
        setInputValue("scheduleEditStartAt", "");
        setInputValue("scheduleEditTime", "");
        return;
      }
      const startAt = toDatetimeLocalValue(inputValue("scheduleEditStartAt"));
      if (startAt) {
        setInputValue("scheduleEditStartAt", startAt);
        setInputValue("scheduleEditTime", startAt.slice(11));
      }
    }

    function updateScheduleEditSummary() {
      const triggerType = inputValue("scheduleEditTriggerType") || "interval";
      const repeatMode = inputValue("scheduleEditRepeatMode") || "forever";
      const rangePreset = inputValue("scheduleEditRangePreset") || "last_n_days";
      const delayValue = numberValue("scheduleEditExecutionDelayValue", 0);
      const delayUnit = inputValue("scheduleEditExecutionDelayUnit") || "seconds";
      const triggerText = triggerType === "interval"
        ? `Every ${inputValue("scheduleEditEvery") || 1} ${inputValue("scheduleEditUnit") || "hours"}`
        : triggerType === "once"
          ? `Once at ${inputValue("scheduleEditRunAt") || "not set"}`
          : `${triggerType} at ${inputValue("scheduleEditTime") || "00:00:00"}`;
      const delayText = delayValue > 0 ? `start ${delayValue} ${delayUnit} later` : "";
      const repeatText = repeatMode === "count"
        ? `${inputValue("scheduleEditRepeatCount") || 1} runs`
        : repeatMode === "until"
          ? `until ${inputValue("scheduleEditUntil") || "not set"}`
          : "forever";
      const rangeText = rangePreset === "fixed"
        ? `${inputValue("scheduleEditRangeStartAt") || "start"} to ${inputValue("scheduleEditRangeEndAt") || "end"}`
        : rangePresetLabel(rangePreset, inputValue("scheduleEditRangeValue") || 1);
      document.getElementById("scheduleEditSummary").textContent = [
        triggerText,
        delayText,
        repeatText,
        rangeText,
      ].filter(Boolean).join(" · ");
    }

    function syncScheduleEditorControls() {
      const triggerType = inputValue("scheduleEditTriggerType") || "interval";
      const repeatMode = inputValue("scheduleEditRepeatMode") || "forever";
      const rangePreset = inputValue("scheduleEditRangePreset") || "last_n_days";
      const rangeType = rangePreset === "fixed" ? "fixed" : "last_n_days";
      setInputValue("scheduleEditDateRangeType", rangeType);
      for (const button of document.querySelectorAll("[data-schedule-trigger]")) {
        button.classList.toggle("active", button.dataset.scheduleTrigger === triggerType);
      }
      syncControlGroup("[data-trigger-field]", triggerType, "data-trigger-field");
      syncControlGroup("[data-repeat-field]", repeatMode, "data-repeat-field");
      syncControlGroup("[data-range-field]", rangeType, "data-range-field");
      syncScheduleStartAt();
      setInputValue("scheduleEditDaysOfWeek", selectedWeekdays().join(", "));
      updateFrequencySummary();
      updateScheduleEditSummary();
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
      const startAtValue = toDatetimeLocalValue(trigger.start_at);
      setInputValue("scheduleEditTime", startAtValue ? startAtValue.slice(11) : trigger.time || "00:00:00");
      setDelayInputs(trigger.execution_delay_seconds || 0);
      setSelectedWeekdays(Array.isArray(trigger.days_of_week) ? trigger.days_of_week : []);
      setInputValue("scheduleEditStartAt", startAtValue);
      setInputValue("scheduleEditRunAt", toDatetimeLocalValue(trigger.run_at));
      setInputValue("scheduleEditRepeatMode", repeat.mode || "forever");
      setInputValue("scheduleEditRepeatCount", repeat.count || "");
      setInputValue("scheduleEditUntil", toDatetimeLocalValue(repeat.until));
      setInputValue("scheduleEditSymbols", Array.isArray(job.symbols) ? job.symbols.join(", ") : "");
      setSelectedFrequencies(Array.isArray(job.frequencies) ? job.frequencies : []);
      setInputValue("scheduleEditRangePreset", rangePresetForDateRange(dateRange));
      setInputValue("scheduleEditDateRangeType", dateRange.type || "last_n_days");
      setInputValue("scheduleEditRangeValue", dateRange.lookback_value || dateRange.days || 1);
      setInputValue(
        "scheduleEditRangeStartAt",
        toDatetimeLocalValue(dateRange.start_at) || dateToDatetimeLocalValue(dateRange.start_date),
      );
      setInputValue(
        "scheduleEditRangeEndAt",
        toDatetimeLocalValue(dateRange.end_at) || dateToDatetimeLocalValue(dateRange.end_date, true),
      );
      setInputValue("scheduleEditPageDelaySeconds", job.page_delay_seconds || 0);
      scheduleEditInput("scheduleEditRefreshExisting").checked = job.refresh_existing !== false;
      setScheduleEditError("");
      syncScheduleEditorControls();
      document.getElementById("scheduleEditBackdrop").hidden = false;
      document.getElementById("scheduleEditDialog").hidden = false;
    }

    function buildScheduleEditPayload(schedule) {
      const config = scheduleConfig(schedule);
      const triggerType = inputValue("scheduleEditTriggerType") || "interval";
      const trigger = {
        type: triggerType,
        timezone: inputValue("scheduleEditTimezone") || "Asia/Shanghai",
        execution_delay_seconds: delaySeconds(
          numberValue("scheduleEditExecutionDelayValue", 0),
          inputValue("scheduleEditExecutionDelayUnit") || "seconds",
        ),
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
        trigger.time = inputValue("scheduleEditTime") || "00:00:00";
      } else if (triggerType === "weekly") {
        trigger.time = inputValue("scheduleEditTime") || "00:00:00";
        trigger.days_of_week = selectedWeekdays();
      }

      const repeatMode = inputValue("scheduleEditRepeatMode") || "forever";
      const repeat = { mode: repeatMode };
      if (repeatMode === "count") {
        repeat.count = numberValue("scheduleEditRepeatCount", 1);
      } else if (repeatMode === "until") {
        repeat.until = inputValue("scheduleEditUntil") || null;
      }

      const rangePreset = inputValue("scheduleEditRangePreset") || "last_n_days";
      const dateRangeType = rangePreset === "fixed" ? "fixed" : "last_n_days";
      const dateRange = {
        type: dateRangeType,
      };
      if (dateRangeType === "fixed") {
        const rangeStartAt = inputValue("scheduleEditRangeStartAt");
        const rangeEndAt = inputValue("scheduleEditRangeEndAt");
        dateRange.start_at = rangeStartAt || null;
        dateRange.end_at = rangeEndAt || null;
        dateRange.start_date = rangeStartAt ? rangeStartAt.slice(0, 10) : null;
        dateRange.end_date = rangeEndAt ? rangeEndAt.slice(0, 10) : null;
      } else {
        const lookbackUnit = rangePresetUnit(rangePreset);
        dateRange.lookback_value = numberValue("scheduleEditRangeValue", 1);
        dateRange.lookback_unit = lookbackUnit;
        dateRange.end_offset_value = 0;
        dateRange.end_offset_unit = "minutes";
        if (lookbackUnit === "days") {
          dateRange.days = dateRange.lookback_value;
        } else {
          dateRange.days = null;
        }
        dateRange.end_offset_days = 0;
      }

      return {
        name: inputValue("scheduleEditName") || config.name || schedule.name,
        trigger,
        repeat,
        job: {
          source_id: inputValue("scheduleEditSourceId") || config.job?.source_id || "",
          symbols: listValue("scheduleEditSymbols"),
          frequencies: selectedFrequencies(),
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

    function confirmScheduleToggle(schedule) {
      const action = schedule.enabled ? "Disable" : "Enable";
      const effect = schedule.enabled
        ? "This will pause future automatic runs for this schedule."
        : "This will resume future automatic runs for this schedule.";
      const name = schedule.name || schedule.schedule_id || "schedule";
      const message = `${action} schedule "${name}"?\\n\\n${effect}`;
      return window.confirm(message);
    }

    async function toggleSchedule(scheduleId) {
      const schedule = scheduleById(scheduleId);
      if (!schedule) {
        return;
      }
      if (!confirmScheduleToggle(schedule)) {
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
        let responsePayload = {};
        try {
          responsePayload = await response.json();
        } catch (error) {
          responsePayload = {};
        }
        if (!response.ok) {
          setScheduleEditError(responsePayload.error || responsePayload.message || `HTTP ${response.status}`);
          return;
        }
        const requestedDelay = Number(payload.trigger?.execution_delay_seconds || 0);
        const savedDelay = Number(responsePayload?.config?.trigger?.execution_delay_seconds || 0);
        if (requestedDelay > 0 && Math.abs(savedDelay - requestedDelay) > 0.001) {
          setScheduleEditError("The data source server does not support execution delay yet. Deploy the updated data-source API, then save again.");
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
        renderScheduleRunPagination(paginatedItems([], 1, dataMonitorState.scheduleRunPageSize));
        rowsEl.innerHTML = `<tr><td class="empty" colspan="7">Unable to load schedule runs</td></tr>`;
        return;
      }
      const runs = recentScheduleRuns();
      const pageInfo = paginatedItems(runs, dataMonitorState.scheduleRunPage, dataMonitorState.scheduleRunPageSize);
      dataMonitorState.scheduleRunPage = pageInfo.page;
      dataMonitorState.scheduleRunPageSize = pageInfo.pageSize;
      renderScheduleRunPagination(pageInfo);
      metaEl.textContent = runs.length ? `${runs.length} runs` : "No run history";
      rowsEl.innerHTML = runs.length ? pageInfo.items.map((run) => {
        const schedule = run.schedule || scheduleById(run.schedule_id) || {};
        const job = run.job_id ? jobById(run.job_id) : null;
        const runStatus = escapeHtml(run.status || "unknown");
        const jobStatus = escapeHtml(job?.status || (run.job_id ? "submitted" : ""));
        const jobLine = job
          ? `${job.success_count || 0}/${job.total_items || 0} ok · failed ${job.failed_count || 0}`
          : run.error || "";
        const rangeText = formatScheduleDateRange(schedule, run.triggered_at || run.due_at);
        return `<tr>
          <td>
            <div class="schedule-name">
              <strong>${escapeHtml(schedule.name || run.schedule_id || "")}</strong>
              <span class="schedule-subline">${escapeHtml(schedule.schedule_id || "")}</span>
            </div>
          </td>
          <td>${escapeHtml(formatScheduleJob(schedule))}</td>
          <td>${escapeHtml(rangeText)}</td>
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
      }).join("") : `<tr><td class="empty" colspan="7">No schedule runs yet</td></tr>`;
    }

    function renderTaskDrawer() {
      syncDrawerTabs();
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
        rowsEl.innerHTML = `<tr><td class="empty" colspan="9">Unable to load crawl tasks</td></tr>`;
        return;
      }
      const source = selectedSource();
      if (!source) {
        metaEl.textContent = "No data sources";
        paginationMetaEl.textContent = "";
        previousButton.disabled = true;
        nextButton.disabled = true;
        rowsEl.innerHTML = `<tr><td class="empty" colspan="9">No crawl tasks</td></tr>`;
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
          <td>${escapeHtml(formatTaskRange(task))}</td>
          <td><span class="task-status ${status}">${status}</span></td>
          <td>${escapeHtml(task.attempts ?? "")}</td>
          <td>${escapeHtml(formatClock(taskUpdatedAt(task)))}</td>
          <td>${escapeHtml(task.last_error || "")}</td>
        </tr>`;
      }).join("") : `<tr><td class="empty" colspan="9">No matching crawl tasks</td></tr>`;
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
      if (!document.getElementById("dataSourceDrawer").hidden && activeDrawerTab() === "tasks") {
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
      syncDrawerTabs();
      const source = selectedSource();
      if (activeDrawerTab() === "tasks" && source && !dataMonitorState.taskPagesBySource[source.source_id]) {
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
    for (const button of document.querySelectorAll("[data-drawer-tab]")) {
      button.addEventListener("click", () => setDrawerTab(button.dataset.drawerTab || "schedules"));
    }
    document.getElementById("scheduleEditForm").addEventListener("submit", saveScheduleEdits);
    document.getElementById("scheduleEditCloseButton").addEventListener("click", closeScheduleEditor);
    document.getElementById("scheduleEditDismissButton").addEventListener("click", closeScheduleEditor);
    document.getElementById("scheduleEditBackdrop").addEventListener("click", closeScheduleEditor);
    document.getElementById("scheduleEditFrequencyToggle").addEventListener("click", (event) => {
      event.stopPropagation();
      toggleFrequencyMenu();
    });
    document.getElementById("scheduleEditFrequencyMenu").addEventListener("click", (event) => {
      event.stopPropagation();
    });
    document.addEventListener("click", closeFrequencyMenu);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        closeFrequencyMenu();
      }
    });
    for (const button of document.querySelectorAll("[data-schedule-trigger]")) {
      button.addEventListener("click", () => setScheduleTriggerMode(button.dataset.scheduleTrigger || "interval"));
    }
    for (const input of document.querySelectorAll("#scheduleEditForm input, #scheduleEditForm select")) {
      input.addEventListener("input", syncScheduleEditorControls);
      input.addEventListener("change", syncScheduleEditorControls);
    }
    document.getElementById("schedulePageSizeSelect").addEventListener("change", (event) => {
      dataMonitorState.schedulePageSize = Number(event.target.value) || 25;
      dataMonitorState.schedulePage = 1;
      renderScheduleRows();
    });
    document.getElementById("schedulePreviousPageButton").addEventListener("click", () => {
      dataMonitorState.schedulePage = Math.max(1, dataMonitorState.schedulePage - 1);
      renderScheduleRows();
    });
    document.getElementById("scheduleNextPageButton").addEventListener("click", () => {
      dataMonitorState.schedulePage += 1;
      renderScheduleRows();
    });
    document.getElementById("scheduleRunPageSizeSelect").addEventListener("change", (event) => {
      dataMonitorState.scheduleRunPageSize = Number(event.target.value) || 25;
      dataMonitorState.scheduleRunPage = 1;
      renderScheduleRunRows();
    });
    document.getElementById("scheduleRunPreviousPageButton").addEventListener("click", () => {
      dataMonitorState.scheduleRunPage = Math.max(1, dataMonitorState.scheduleRunPage - 1);
      renderScheduleRunRows();
    });
    document.getElementById("scheduleRunNextPageButton").addEventListener("click", () => {
      dataMonitorState.scheduleRunPage += 1;
      renderScheduleRunRows();
    });
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
