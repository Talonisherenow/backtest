from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from backtest.data_source.api import DataSourceApi


def serve_data_source_api(
    api: DataSourceApi,
    host: str = "127.0.0.1",
    port: int = 8768,
) -> None:
    server = ThreadingHTTPServer((host, port), make_data_source_handler(api))
    server.serve_forever()


def make_data_source_handler(api: DataSourceApi):
    class DataSourceRequestHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:
            self._send_empty(204)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            try:
                if parsed.path == "/api/health":
                    self._send_json(200, api.health())
                elif parsed.path == "/api/data-sources":
                    self._send_json(200, api.data_sources())
                elif parsed.path == "/api/kline/manifest":
                    self._send_json(200, api.kline_manifest())
                elif parsed.path == "/api/kline/bars":
                    self._send_json(200, api.kline_bars(**self._bars_args(query)))
                elif parsed.path == "/api/data/tasks":
                    self._send_json(200, api.tasks(self._required(query, "source_id")))
                elif parsed.path == "/api/data/inventory":
                    self._send_json(200, api.inventory(self._required(query, "source_id")))
                elif parsed.path == "/api/data/jobs":
                    self._send_json(200, api.jobs())
                elif parsed.path.startswith("/api/data/jobs/"):
                    self._send_json(200, api.job(parsed.path.rsplit("/", 1)[-1]))
                else:
                    self._send_json(404, {"error": "Not found"})
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/data/jobs":
                    self._send_json(200, api.submit_job(self._read_json()))
                elif parsed.path == "/api/data/retry-failed":
                    payload = self._read_json()
                    source_id = payload.get("source_id")
                    if not source_id:
                        raise ValueError("source_id is required")
                    self._send_json(200, api.retry_failed(str(source_id)))
                else:
                    self._send_json(404, {"error": "Not found"})
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": str(exc)})

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _bars_args(self, query: dict[str, list[str]]) -> dict[str, Any]:
            args: dict[str, Any] = {
                "source_id": self._optional(query, "source_id"),
                "symbol": self._required(query, "symbol"),
                "frequency": self._required(query, "frequency"),
                "adjust": self._optional(query, "adjust"),
                "limit": int(
                    self._optional(query, "limit") or api.config.default_window_size
                ),
                "anchor": self._optional(query, "anchor"),
                "start": self._optional(query, "start"),
            }
            offset = self._optional(query, "offset")
            if offset is not None:
                args["offset"] = int(offset)
            return args

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length == 0:
                return {}
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload

        def _required(self, query: dict[str, list[str]], key: str) -> str:
            value = self._optional(query, key)
            if value is None or value == "":
                raise ValueError(f"{key} is required")
            return value

        @staticmethod
        def _optional(query: dict[str, list[str]], key: str) -> str | None:
            values = query.get(key)
            return values[0] if values else None

        def _send_json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_empty(self, status: int) -> None:
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    return DataSourceRequestHandler
