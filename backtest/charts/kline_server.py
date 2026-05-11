from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from backtest.charts.kline_service import KlineCacheService, KlineSource
from backtest.charts.kline_viewer import render_kline_viewer_html


def serve_kline_viewer(
    *,
    sources: list[KlineSource] | None = None,
    bars_root: Path | str = Path("data/bars"),
    host: str = "127.0.0.1",
    port: int = 8765,
    adjust: str = "qfq",
    universe_path: Path | None = None,
    source_roots: list[tuple[str, Path]] | None = None,
    frequencies: list[str] | None = None,
    symbols: list[str] | None = None,
    default_window_size: int = 5000,
) -> None:
    service = KlineCacheService(
        bars_root=Path(bars_root),
        sources=sources,
        adjust=adjust,
        universe_path=universe_path,
        source_roots=source_roots,
        frequencies=frequencies,
        symbols=symbols,
    )
    payload = {
        "mode": "dynamic",
        "adjust": adjust,
        "default_window_size": default_window_size,
    }
    html = render_kline_viewer_html(payload).encode("utf-8")

    class KlineViewerHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib hook
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/kline", "/crypto_kline_viewer.html", "/kline_viewer.html"}:
                self._send_bytes(html, "text/html; charset=utf-8")
                return
            if parsed.path == "/api/manifest":
                self._send_json(service.manifest(default_window_size=default_window_size))
                return
            if parsed.path == "/api/bars":
                self._handle_bars(parsed.query)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

        def log_message(self, format: str, *args: object) -> None:
            return

        def _handle_bars(self, query: str) -> None:
            params = parse_qs(query)
            try:
                symbol = self._required(params, "symbol")
                frequency = self._required(params, "frequency")
                result = service.bars(
                    source_id=self._optional(params, "source_id"),
                    symbol=unquote(symbol),
                    frequency=frequency,
                    adjust=self._optional(params, "adjust"),
                    limit=self._int_param(params, "limit", default_window_size),
                    offset=self._optional_int(params, "offset"),
                    start=self._optional(params, "start"),
                    anchor=self._optional(params, "anchor"),
                )
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._send_json(result)

        def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._send_bytes(body, "application/json; charset=utf-8", status=status)

        def _send_bytes(
            self,
            body: bytes,
            content_type: str,
            *,
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
            value = KlineViewerHandler._optional(params, name)
            if value is None:
                raise ValueError(f"Missing required parameter: {name}")
            return value

        @staticmethod
        def _optional(params: dict[str, list[str]], name: str) -> str | None:
            values = params.get(name)
            return values[0] if values else None

        @staticmethod
        def _int_param(params: dict[str, list[str]], name: str, default: int) -> int:
            value = KlineViewerHandler._optional(params, name)
            return int(value) if value not in {None, ""} else default

        @staticmethod
        def _optional_int(params: dict[str, list[str]], name: str) -> int | None:
            value = KlineViewerHandler._optional(params, name)
            return int(value) if value not in {None, ""} else None

    server = ThreadingHTTPServer((host, port), KlineViewerHandler)
    print(f"Serving K-line viewer at http://{host}:{port}/kline")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
