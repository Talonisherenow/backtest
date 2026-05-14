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
    index_html = render_workbench_index_html().encode("utf-8")
    kline_html = render_kline_viewer_html(
        build_kline_shell_payload(
            default_window_size=default_window_size,
            data_api_base_url=data_api_base_url,
        )
    ).encode("utf-8")
    strategy_html = render_strategy_results_catalog_html(
        {"mode": "dynamic", "title": "Strategy Results", "links": {"workbench_home": "/"}}
    ).encode("utf-8")

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


def render_workbench_index_html() -> str:
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
      --text: #1d2733;
      --muted: #667789;
      --blue: #1d5fd1;
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
    strong { font-size: 17px; }
    span { color: var(--muted); font-size: 13px; line-height: 1.45; }
  </style>
</head>
<body>
  <header>
    <h1>Backtest Workbench</h1>
    <div class="subtitle">One local service for strategy results and market K-line inspection.</div>
  </header>
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
</body>
</html>
"""
