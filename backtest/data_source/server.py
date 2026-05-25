from __future__ import annotations

import hmac
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

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
            if not self._is_authorized():
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
                return
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            try:
                if parsed.path == "/api/health":
                    self._send_json(200, api.health())
                elif parsed.path == "/api/data-sources":
                    self._send_json(200, api.data_sources())
                elif parsed.path == "/api/instrument-sources":
                    self._send_json(200, api.instrument_sources())
                elif parsed.path == "/api/instrument-sync/schedules":
                    self._send_json(200, api.instrument_sync_schedules())
                elif (
                    parsed.path.endswith("/runs")
                    and parsed.path.startswith("/api/instrument-sync/schedules/")
                ):
                    self._send_json(
                        200,
                        api.instrument_sync_schedule_runs(
                            self._instrument_sync_schedule_id_for_suffix(parsed.path, "/runs")
                        ),
                    )
                elif parsed.path.startswith("/api/instrument-sync/schedules/"):
                    self._send_json(
                        200,
                        api.instrument_sync_schedule(
                            self._path_id(parsed.path, "/api/instrument-sync/schedules/")
                        ),
                    )
                elif parsed.path == "/api/kline/manifest":
                    self._send_json(200, api.kline_manifest())
                elif parsed.path == "/api/kline/bars":
                    self._send_json(200, api.kline_bars(**self._bars_args(query)))
                elif parsed.path == "/api/data/tasks/summary":
                    self._send_json(200, api.task_summary(self._required(query, "source_id")))
                elif parsed.path == "/api/data/tasks":
                    self._send_json(200, api.tasks(**self._task_args(query)))
                elif parsed.path == "/api/data/inventory":
                    self._send_json(200, api.inventory(self._required(query, "source_id")))
                elif parsed.path == "/api/instruments":
                    self._send_json(200, api.instruments(**self._instrument_list_args(query)))
                elif parsed.path.startswith("/api/instruments/"):
                    self._send_json(
                        200,
                        api.instrument(
                            self._path_id(parsed.path, "/api/instruments/"),
                            source_id=self._optional(query, "source_id"),
                        ),
                    )
                elif parsed.path == "/api/instrument-tags":
                    self._send_json(
                        200,
                        api.instrument_tags(source_id=self._optional(query, "source_id")),
                    )
                elif parsed.path == "/api/data/schedule-options":
                    self._send_json(200, api.schedule_options())
                elif parsed.path == "/api/data/schedules":
                    self._send_json(200, api.schedules())
                elif parsed.path.endswith("/runs") and parsed.path.startswith("/api/data/schedules/"):
                    self._send_json(200, api.schedule_runs(self._schedule_id_for_suffix(parsed.path, "/runs")))
                elif parsed.path.startswith("/api/data/schedules/"):
                    self._send_json(200, api.schedule(parsed.path.rsplit("/", 1)[-1]))
                elif parsed.path == "/api/data/jobs":
                    self._send_json(200, api.jobs())
                elif parsed.path.startswith("/api/data/jobs/"):
                    self._send_json(200, api.job(parsed.path.rsplit("/", 1)[-1]))
                else:
                    self._send_json(404, {"error": "Not found"})
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

        def do_POST(self) -> None:
            if not self._is_authorized():
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
                return
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/instrument-sync/schedules":
                    self._send_json(200, api.create_instrument_sync_schedule(self._read_json()))
                elif (
                    parsed.path.endswith("/enable")
                    and parsed.path.startswith("/api/instrument-sync/schedules/")
                ):
                    self._send_json(
                        200,
                        api.enable_instrument_sync_schedule(
                            self._instrument_sync_schedule_id_for_suffix(
                                parsed.path,
                                "/enable",
                            )
                        ),
                    )
                elif (
                    parsed.path.endswith("/disable")
                    and parsed.path.startswith("/api/instrument-sync/schedules/")
                ):
                    self._send_json(
                        200,
                        api.disable_instrument_sync_schedule(
                            self._instrument_sync_schedule_id_for_suffix(
                                parsed.path,
                                "/disable",
                            )
                        ),
                    )
                elif (
                    parsed.path.endswith("/run-now")
                    and parsed.path.startswith("/api/instrument-sync/schedules/")
                ):
                    self._send_json(
                        200,
                        api.run_instrument_sync_schedule_now(
                            self._instrument_sync_schedule_id_for_suffix(
                                parsed.path,
                                "/run-now",
                            )
                        ),
                    )
                elif parsed.path == "/api/data/schedules":
                    self._send_json(200, api.create_schedule(self._read_json()))
                elif parsed.path.endswith("/enable") and parsed.path.startswith("/api/data/schedules/"):
                    self._send_json(200, api.enable_schedule(self._schedule_id_for_suffix(parsed.path, "/enable")))
                elif parsed.path.endswith("/disable") and parsed.path.startswith("/api/data/schedules/"):
                    self._send_json(200, api.disable_schedule(self._schedule_id_for_suffix(parsed.path, "/disable")))
                elif parsed.path.endswith("/run-now") and parsed.path.startswith("/api/data/schedules/"):
                    self._send_json(200, api.run_schedule_now(self._schedule_id_for_suffix(parsed.path, "/run-now")))
                elif parsed.path == "/api/data/jobs":
                    self._send_json(200, api.submit_job(self._read_json()))
                elif parsed.path == "/api/instrument-sync/run":
                    self._send_json(200, api.run_instrument_sync(self._read_json()))
                elif parsed.path == "/api/data/retry-failed":
                    payload = self._read_json()
                    source_id = payload.get("source_id")
                    if not source_id:
                        raise ValueError("source_id is required")
                    self._send_json(200, api.retry_failed(str(source_id)))
                elif parsed.path == "/api/instruments":
                    self._send_json(200, api.create_instrument(self._read_json()))
                elif parsed.path == "/api/instrument-tags":
                    self._send_json(200, api.create_instrument_tag(self._read_json()))
                elif (
                    parsed.path.startswith("/api/instrument-tags/")
                    and parsed.path.endswith("/members")
                ):
                    self._send_json(
                        200,
                        api.add_instrument_tag_members(
                            self._tag_id_for_members_path(parsed.path),
                            self._read_json(),
                        ),
                    )
                else:
                    self._send_json(404, {"error": "Not found"})
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": str(exc)})
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

        def do_PATCH(self) -> None:
            if not self._is_authorized():
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
                return
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            try:
                if parsed.path.startswith("/api/instrument-sync/schedules/"):
                    self._send_json(
                        200,
                        api.update_instrument_sync_schedule(
                            self._path_id(parsed.path, "/api/instrument-sync/schedules/"),
                            self._read_json(),
                        ),
                    )
                elif parsed.path.startswith("/api/data/schedules/"):
                    self._send_json(
                        200,
                        api.update_schedule(parsed.path.rsplit("/", 1)[-1], self._read_json()),
                    )
                elif parsed.path.startswith("/api/instruments/"):
                    self._send_json(
                        200,
                        api.update_instrument(
                            self._path_id(parsed.path, "/api/instruments/"),
                            self._read_json(),
                            source_id=self._optional(query, "source_id"),
                        ),
                    )
                elif parsed.path.startswith("/api/instrument-tags/"):
                    self._send_json(
                        200,
                        api.update_instrument_tag(
                            self._path_id(parsed.path, "/api/instrument-tags/"),
                            self._read_json(),
                            source_id=self._optional(query, "source_id"),
                        ),
                    )
                else:
                    self._send_json(404, {"error": "Not found"})
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": str(exc)})
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

        def do_DELETE(self) -> None:
            if not self._is_authorized():
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
                return
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            try:
                if parsed.path.startswith("/api/instrument-sync/schedules/"):
                    self._send_json(
                        200,
                        api.delete_instrument_sync_schedule(
                            self._path_id(parsed.path, "/api/instrument-sync/schedules/")
                        ),
                    )
                elif parsed.path.startswith("/api/data/schedules/"):
                    self._send_json(200, api.delete_schedule(parsed.path.rsplit("/", 1)[-1]))
                elif (
                    parsed.path.startswith("/api/instrument-tags/")
                    and "/members/" in parsed.path
                ):
                    tag_id, instrument_id = self._tag_member_ids(parsed.path)
                    self._send_json(
                        200,
                        api.remove_instrument_tag_member(
                            tag_id,
                            instrument_id,
                            source_id=self._optional(query, "source_id"),
                        ),
                    )
                elif parsed.path.startswith("/api/instruments/"):
                    self._send_json(
                        200,
                        api.delete_instrument(
                            self._path_id(parsed.path, "/api/instruments/"),
                            source_id=self._optional(query, "source_id"),
                        ),
                    )
                elif parsed.path.startswith("/api/instrument-tags/"):
                    self._send_json(
                        200,
                        api.delete_instrument_tag(
                            self._path_id(parsed.path, "/api/instrument-tags/"),
                            source_id=self._optional(query, "source_id"),
                        ),
                    )
                else:
                    self._send_json(404, {"error": "Not found"})
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

        def do_PUT(self) -> None:
            if not self._is_authorized():
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
                return
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            try:
                if (
                    parsed.path.startswith("/api/instrument-tags/")
                    and parsed.path.endswith("/members")
                ):
                    self._send_json(
                        200,
                        api.replace_instrument_tag_members(
                            self._tag_id_for_members_path(parsed.path),
                            self._read_json(),
                            source_id=self._optional(query, "source_id"),
                        ),
                    )
                else:
                    self._send_json(404, {"error": "Not found"})
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": str(exc)})
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _is_authorized(self) -> bool:
            expected_token = api.config.api_token
            if expected_token is None:
                return True
            scheme, _, provided_token = self.headers.get("Authorization", "").partition(" ")
            if scheme.lower() != "bearer" or not provided_token:
                return False
            return hmac.compare_digest(provided_token, expected_token)

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

        def _task_args(self, query: dict[str, list[str]]) -> dict[str, Any]:
            page = self._optional(query, "page")
            page_size = self._optional(query, "page_size")
            args: dict[str, Any] = {
                "source_id": self._required(query, "source_id"),
                "symbol": self._optional(query, "symbol"),
                "frequencies": query.get("frequency", []),
                "statuses": query.get("status", []),
            }
            if page is not None:
                args["page"] = int(page)
            if page_size is not None:
                args["page_size"] = int(page_size)
            return args

        def _instrument_list_args(self, query: dict[str, list[str]]) -> dict[str, Any]:
            args: dict[str, Any] = {
                "source_id": self._optional(query, "source_id"),
                "q": self._optional(query, "q"),
                "tag": self._optional(query, "tag"),
            }
            limit = self._optional(query, "limit")
            offset = self._optional(query, "offset")
            if limit is not None:
                args["limit"] = int(limit)
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

        @staticmethod
        def _schedule_id_for_suffix(path: str, suffix: str) -> str:
            return path.removeprefix("/api/data/schedules/").removesuffix(suffix).strip("/")

        @staticmethod
        def _instrument_sync_schedule_id_for_suffix(path: str, suffix: str) -> str:
            return path.removeprefix("/api/instrument-sync/schedules/").removesuffix(suffix).strip("/")

        @staticmethod
        def _path_id(path: str, prefix: str) -> str:
            value = unquote(path.removeprefix(prefix).strip("/"))
            if not value:
                raise ValueError("path id is required")
            return value

        @staticmethod
        def _tag_id_for_members_path(path: str) -> str:
            suffix = path.removeprefix("/api/instrument-tags/")
            tag_id = suffix.removesuffix("/members")
            value = unquote(tag_id.strip("/"))
            if not value:
                raise ValueError("tag_id is required")
            return value

        @staticmethod
        def _tag_member_ids(path: str) -> tuple[str, str]:
            suffix = path.removeprefix("/api/instrument-tags/")
            tag_id, separator, instrument_id = suffix.partition("/members/")
            if not separator:
                raise ValueError("tag member path is invalid")
            decoded_tag = unquote(tag_id.strip("/"))
            decoded_instrument = unquote(instrument_id.strip("/"))
            if not decoded_tag or not decoded_instrument:
                raise ValueError("tag_id and instrument_id are required")
            return decoded_tag, decoded_instrument

        def _send_json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._cors_headers()
            if status == HTTPStatus.UNAUTHORIZED:
                self.send_header("WWW-Authenticate", "Bearer")
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
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    return DataSourceRequestHandler
