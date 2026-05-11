from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from backtest.charts.strategy_account_viewer import render_strategy_account_viewer_html
from backtest.charts.strategy_order_drilldown_viewer import render_strategy_order_drilldown_viewer_html
from backtest.charts.strategy_results_catalog import render_strategy_results_catalog_html
from backtest.charts.strategy_results_service import StrategyResultsService


def serve_strategy_results(
    *,
    results_roots: list[Path],
    bars_root: Path,
    host: str = "127.0.0.1",
    port: int = 8766,
) -> None:
    service = StrategyResultsService(results_roots=results_roots, bars_root=bars_root)
    html = render_strategy_results_catalog_html({"mode": "dynamic", "title": "Strategy Results"}).encode("utf-8")

    class StrategyResultsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            if parsed.path in {"/", "/strategy-results"}:
                self._send_bytes(html, "text/html; charset=utf-8")
                return
            if parsed.path == "/api/strategy-results":
                self._send_json(service.catalog())
                return
            if parsed.path == "/api/strategy-results/account":
                self._handle_account_json(params)
                return
            if parsed.path == "/api/strategy-results/drilldown":
                self._handle_drilldown_json(params)
                return
            if parsed.path == "/strategy-results/account":
                self._handle_account_html(params)
                return
            if parsed.path == "/strategy-results/drilldown":
                self._handle_drilldown_html(params)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

        def log_message(self, format: str, *args: object) -> None:
            return

        def _handle_account_json(self, params: dict[str, list[str]]) -> None:
            try:
                self._send_json(service.account_payload(self._required(params, "case_id")))
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def _handle_drilldown_json(self, params: dict[str, list[str]]) -> None:
            try:
                self._send_json(
                    service.drilldown_payload(
                        self._required(params, "case_id"),
                        default_symbol=self._optional(params, "symbol"),
                    )
                )
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def _handle_account_html(self, params: dict[str, list[str]]) -> None:
            try:
                body = render_strategy_account_viewer_html(
                    service.account_payload(self._required(params, "case_id"))
                ).encode("utf-8")
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_bytes(body, "text/html; charset=utf-8")

        def _handle_drilldown_html(self, params: dict[str, list[str]]) -> None:
            try:
                body = render_strategy_order_drilldown_viewer_html(
                    service.drilldown_payload(
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
            value = StrategyResultsHandler._optional(params, name)
            if value is None:
                raise ValueError(f"Missing required parameter: {name}")
            return value

        @staticmethod
        def _optional(params: dict[str, list[str]], name: str) -> str | None:
            values = params.get(name)
            if not values:
                return None
            return unquote(values[0])

    server = ThreadingHTTPServer((host, port), StrategyResultsHandler)
    print(f"Serving strategy results viewer at http://{host}:{port}/strategy-results")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
