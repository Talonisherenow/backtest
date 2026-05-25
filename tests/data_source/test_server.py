from datetime import date, datetime
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json

import pandas as pd

from backtest.core.enums import AdjustMode, Frequency
from backtest.data.metadata import MetadataStore
from backtest.data.store import ParquetBarStore
from backtest.data.tasks import CrawlTaskManager
from backtest.data_source.api import DataSourceApi
from backtest.data_source.config import DataSourceServerConfig, DataSourceSpec
from backtest.data_source.jobs import DataSourceJobRegistry
from backtest.data_source.schedules import DataSourceScheduleService, DataSourceScheduleStore
from backtest.data_source.server import make_data_source_handler


def _api(
    tmp_path: Path,
    *,
    row_count: int = 2,
    default_window_size: int = 1,
    api_token: str | None = None,
) -> DataSourceApi:
    bars_root = tmp_path / "bars"
    ParquetBarStore(bars_root).write_bars(
        pd.DataFrame(
            {
                "date": pd.date_range("2025-01-01", periods=row_count, freq="D"),
                "symbol": ["000001.SZ"] * row_count,
                "open": [10.0 + index for index in range(row_count)],
                "high": [11.0 + index for index in range(row_count)],
                "low": [9.0 + index for index in range(row_count)],
                "close": [10.5 + index for index in range(row_count)],
                "volume": [1000 + index for index in range(row_count)],
                "amount": [10000 + index for index in range(row_count)],
                "frequency": ["1d"] * row_count,
                "adjust": ["qfq"] * row_count,
            }
        )
    )
    spec = DataSourceSpec(
        source_id="a_share",
        source_label="A-share",
        asset_class="equity",
        bars_root=bars_root,
        metadata_path=tmp_path / "metadata.sqlite",
        adjust="qfq",
        catalog_source="akshare",
    )
    task_id = CrawlTaskManager(MetadataStore(spec.metadata_path)).create_task(
        "000001.SZ",
        Frequency.DAILY,
        AdjustMode.QFQ,
        date(2025, 1, 1),
        date(2025, 1, 2),
        "akshare",
    )
    CrawlTaskManager(MetadataStore(spec.metadata_path)).mark_failed(task_id, "timeout")
    return DataSourceApi(
        DataSourceServerConfig(
            sources=[spec],
            default_window_size=default_window_size,
            api_token=api_token,
        ),
        DataSourceJobRegistry(
            lambda config: type(
                "Result",
                (),
                {
                    "name": config.name,
                    "started_at": datetime(2025, 1, 1, 10, 0, 0),
                    "finished_at": datetime(2025, 1, 1, 10, 1, 0),
                    "total_items": 0,
                    "success_count": 0,
                    "failed_count": 0,
                    "total_rows": 0,
                },
            )(),
            now=lambda: datetime(2025, 1, 1, 9, 0, 0),
            run_inline=True,
        ),
    )


def _server(
    tmp_path: Path,
    *,
    row_count: int = 2,
    default_window_size: int = 1,
    api_token: str | None = None,
):
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        make_data_source_handler(
            _api(
                tmp_path,
                row_count=row_count,
                default_window_size=default_window_size,
                api_token=api_token,
            )
        ),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _server_for_api(api: DataSourceApi):
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_data_source_handler(api))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _json_request(base_url: str, path: str, *, method: str = "GET", payload=None, headers=None):
    data = None
    headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(base_url + path, data=data, headers=headers, method=method)
    with urlopen(request, timeout=5) as response:
        body = response.read().decode("utf-8")
        return response.status, dict(response.headers), json.loads(body) if body else None


def test_get_routes_and_cors_headers(tmp_path: Path):
    server = _server(tmp_path)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, headers, health = _json_request(base_url, "/api/health")
        _, _, sources = _json_request(base_url, "/api/data-sources")
        _, _, manifest = _json_request(base_url, "/api/kline/manifest")
        query = urlencode(
            {
                "source_id": "a_share",
                "symbol": "000001.SZ",
                "frequency": "1d",
                "adjust": "qfq",
                "limit": 1,
                "anchor": "latest",
            }
        )
        _, _, bars = _json_request(base_url, f"/api/kline/bars?{query}")
        _, _, tasks = _json_request(base_url, "/api/data/tasks?source_id=a_share")
        _, _, task_summary = _json_request(base_url, "/api/data/tasks/summary?source_id=a_share")
        _, _, inventory = _json_request(base_url, "/api/data/inventory?source_id=a_share")
        _, _, jobs = _json_request(base_url, "/api/data/jobs")

        assert status == 200
        assert headers["Access-Control-Allow-Origin"] == "*"
        assert health["status"] == "ok"
        assert sources["sources"][0]["source_id"] == "a_share"
        assert manifest["default_window_size"] == 1
        assert bars["loaded_rows"] == 1
        assert tasks["tasks"][0]["status"] == "failed"
        assert tasks["page"] == 1
        assert tasks["page_size"] == 50
        assert tasks["total"] == 1
        assert task_summary["status_counts"] == {"failed": 1}
        assert task_summary["frequency_counts"] == {"1d": 1}
        assert inventory == {"records": []}
        assert jobs == {"jobs": []}
    finally:
        server.shutdown()
        server.server_close()


def test_instrument_sync_schedule_http_routes(tmp_path: Path):
    api = _api(tmp_path)
    server = _server_for_api(api)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, _, created = _json_request(
            base_url,
            "/api/instrument-sync/schedules",
            method="POST",
            payload={
                "name": "a-share once",
                "enabled": False,
                "source_id": "a_share",
                "trigger": {
                    "type": "once",
                    "run_at": "2026-05-25T09:00:00+08:00",
                },
            },
        )
        schedule_id = created["schedule_id"]
        _, _, listed = _json_request(base_url, "/api/instrument-sync/schedules")
        _, _, enabled = _json_request(
            base_url,
            f"/api/instrument-sync/schedules/{schedule_id}/enable",
            method="POST",
            payload={},
        )
        _, _, disabled = _json_request(
            base_url,
            f"/api/instrument-sync/schedules/{schedule_id}/disable",
            method="POST",
            payload={},
        )
        _, _, deleted = _json_request(
            base_url,
            f"/api/instrument-sync/schedules/{schedule_id}",
            method="DELETE",
        )

        assert listed["schedules"][0]["schedule_id"] == schedule_id
        assert enabled["enabled"] is True
        assert disabled["enabled"] is False
        assert deleted == {"deleted": schedule_id}
    finally:
        server.shutdown()
        server.server_close()


def test_kline_bars_uses_config_default_window_size_when_limit_is_omitted(tmp_path: Path):
    server = _server(tmp_path, row_count=5, default_window_size=4)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        query = urlencode(
            {
                "source_id": "a_share",
                "symbol": "000001.SZ",
                "frequency": "1d",
                "adjust": "qfq",
                "anchor": "latest",
            }
        )
        _, _, bars = _json_request(base_url, f"/api/kline/bars?{query}")

        assert bars["loaded_rows"] == 4
        assert bars["limit"] == 4
    finally:
        server.shutdown()
        server.server_close()


def test_get_route_returns_json_error_for_unexpected_failure():
    from http.server import ThreadingHTTPServer

    class BrokenApi:
        config = type("Config", (), {"api_token": None})()

        def kline_manifest(self):
            raise OSError("corrupt parquet")

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_data_source_handler(BrokenApi()))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        try:
            _json_request(base_url, "/api/kline/manifest")
        except HTTPError as exc:
            assert exc.code == 500
            assert json.loads(exc.read().decode("utf-8")) == {"error": "corrupt parquet"}
        else:
            raise AssertionError("expected HTTPError")
    finally:
        server.shutdown()
        server.server_close()


def test_task_route_supports_pagination_symbol_and_multi_select_filters(tmp_path: Path):
    server = _server(tmp_path)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        query = urlencode(
            [
                ("source_id", "a_share"),
                ("page", "1"),
                ("page_size", "1"),
                ("symbol", "000001"),
                ("frequency", "1d"),
                ("frequency", "4h"),
                ("status", "failed"),
                ("status", "running"),
            ]
        )

        _, _, tasks = _json_request(base_url, f"/api/data/tasks?{query}")

        assert tasks["source_id"] == "a_share"
        assert tasks["page"] == 1
        assert tasks["page_size"] == 1
        assert tasks["total"] == 1
        assert tasks["filters"] == {
            "symbol": "000001",
            "frequencies": ["1d", "4h"],
            "statuses": ["failed", "running"],
        }
        assert tasks["tasks"][0]["symbol"] == "000001.SZ"
    finally:
        server.shutdown()
        server.server_close()


def test_task_route_rejects_invalid_pagination(tmp_path: Path):
    server = _server(tmp_path)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        try:
            _json_request(base_url, "/api/data/tasks?source_id=a_share&page=0")
        except HTTPError as exc:
            assert exc.code == 400
            assert "page must be greater than or equal to 1" in json.loads(
                exc.read().decode("utf-8")
            )["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_post_job_retry_failed_options_and_error_routes(tmp_path: Path):
    server = _server(tmp_path)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        status, headers, _ = _json_request(base_url, "/api/data/jobs", method="OPTIONS")
        assert status == 204
        assert headers["Access-Control-Allow-Methods"]

        _, _, job = _json_request(
            base_url,
            "/api/data/jobs",
            method="POST",
            payload={
                "name": "server job",
                "source": "ccxt",
                "exchange": "bitget",
                "symbols": ["BTC/USDT"],
                "frequencies": ["1d"],
                "adjust": "none",
                "start_date": "2025-01-01",
                "end_date": "2025-01-02",
            },
        )
        _, _, same_job = _json_request(base_url, f"/api/data/jobs/{job['job_id']}")
        _, _, retry = _json_request(
            base_url,
            "/api/data/retry-failed",
            method="POST",
            payload={"source_id": "a_share"},
        )

        assert job["status"] == "success"
        assert same_job["job_id"] == job["job_id"]
        assert retry["queued"] == 1

        try:
            _json_request(base_url, "/api/unknown")
        except HTTPError as exc:
            assert exc.code == 404
            assert json.loads(exc.read().decode("utf-8")) == {"error": "Not found"}

        try:
            _json_request(base_url, "/api/data/tasks")
        except HTTPError as exc:
            assert exc.code == 400
            assert "source_id is required" in json.loads(exc.read().decode("utf-8"))["error"]
    finally:
        server.shutdown()
        server.server_close()


def test_instrument_http_routes(tmp_path: Path):
    api = _api(tmp_path)
    server = _server_for_api(api)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, _, created = _json_request(
            base_url,
            "/api/instruments",
            method="POST",
            payload={
                "instrument_id": "btc/usdt",
                "symbol": "btc/usdt",
                "name": "Bitcoin",
                "source_id": "a_share",
            },
        )
        _, _, tag = _json_request(
            base_url,
            "/api/instrument-tags",
            method="POST",
            payload={"tag_id": "watchlist", "name": "Watchlist", "source_id": "a_share"},
        )
        _, _, members = _json_request(
            base_url,
            "/api/instrument-tags/watchlist/members",
            method="POST",
            payload={"source_id": "a_share", "instrument_ids": ["BTC/USDT"]},
        )
        _, _, filtered = _json_request(
            base_url,
            "/api/instruments?source_id=a_share&tag=Watchlist",
        )
        _, _, detail = _json_request(
            base_url,
            "/api/instruments/BTC%2FUSDT?source_id=a_share",
        )
        _, _, tags = _json_request(base_url, "/api/instrument-tags?source_id=a_share")
        _, _, updated = _json_request(
            base_url,
            "/api/instruments/BTC%2FUSDT?source_id=a_share",
            method="PATCH",
            payload={"name": "BTCUSDT"},
        )
        _, _, replaced = _json_request(
            base_url,
            "/api/instrument-tags/watchlist/members?source_id=a_share",
            method="PUT",
            payload={"instrument_ids": []},
        )
        _, _, readded = _json_request(
            base_url,
            "/api/instrument-tags/watchlist/members?source_id=a_share",
            method="POST",
            payload={"instrument_ids": ["BTC/USDT"]},
        )
        _, _, removed = _json_request(
            base_url,
            "/api/instrument-tags/watchlist/members/BTC%2FUSDT?source_id=a_share",
            method="DELETE",
        )
        _, _, renamed_tag = _json_request(
            base_url,
            "/api/instrument-tags/watchlist?source_id=a_share",
            method="PATCH",
            payload={"name": "Favorites"},
        )
        _, _, deleted_tag = _json_request(
            base_url,
            "/api/instrument-tags/watchlist?source_id=a_share",
            method="DELETE",
        )
        _, _, deleted_instrument = _json_request(
            base_url,
            "/api/instruments/BTC%2FUSDT?source_id=a_share",
            method="DELETE",
        )

        assert created["instrument_id"] == "BTC/USDT"
        assert tag["name"] == "Watchlist"
        assert members["members"][0]["instrument_id"] == "BTC/USDT"
        assert filtered["total"] == 1
        assert detail["tags"][0]["tag_id"] == "watchlist"
        assert tags["tags"][0]["member_count"] == 1
        assert updated["name"] == "BTCUSDT"
        assert replaced["members"] == []
        assert readded["members"][0]["instrument_id"] == "BTC/USDT"
        assert removed["members"] == []
        assert renamed_tag["name"] == "Favorites"
        assert deleted_tag == {"deleted": "watchlist"}
        assert deleted_instrument == {"deleted": "BTC/USDT"}
    finally:
        server.shutdown()
        server.server_close()


def test_instrument_source_sync_http_routes(tmp_path: Path):
    api = _api(tmp_path)
    spec = api.config.source("a_share")
    universe = tmp_path / "a_share.csv"
    pd.DataFrame(
        [{"symbol": "000001.SZ", "name": "平安银行", "exchange": "SZ", "industry": "bank"}]
    ).to_csv(universe, index=False)
    object.__setattr__(spec, "universe_path", universe)

    server = _server_for_api(api)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, _, sources = _json_request(base_url, "/api/instrument-sources")
        _, _, sync_result = _json_request(
            base_url,
            "/api/instrument-sync/run",
            method="POST",
            payload={"source_id": "a_share"},
        )
        _, _, instruments = _json_request(base_url, "/api/instruments?source_id=a_share")
        _, _, tags = _json_request(base_url, "/api/instrument-tags")

        assert sources["sources"][0]["source_id"] == "a_share"
        assert sources["sources"][0]["provider_type"] == "universe_csv"
        assert sync_result["created"] == 1
        assert instruments["total"] == 1
        assert tags["tags"][0]["tag_id"] == "a_share"
    finally:
        server.shutdown()
        server.server_close()


def test_server_requires_bearer_token_when_configured(tmp_path: Path):
    server = _server(tmp_path, api_token="secret-token")
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        try:
            _json_request(base_url, "/api/health")
        except HTTPError as exc:
            assert exc.code == 401
            assert exc.headers["Access-Control-Allow-Origin"] == "*"
            assert json.loads(exc.read().decode("utf-8")) == {"error": "Unauthorized"}

        try:
            _json_request(
                base_url,
                "/api/health",
                headers={"Authorization": "Bearer wrong-token"},
            )
        except HTTPError as exc:
            assert exc.code == 401

        try:
            _json_request(
                base_url,
                "/api/data/jobs",
                method="POST",
                payload={"name": "blocked"},
            )
        except HTTPError as exc:
            assert exc.code == 401

        status, headers, _ = _json_request(base_url, "/api/health", method="OPTIONS")
        assert status == 204
        assert "Authorization" in headers["Access-Control-Allow-Headers"]

        status, _, health = _json_request(
            base_url,
            "/api/health",
            headers={"Authorization": "Bearer secret-token"},
        )
        assert status == 200
        assert health["status"] == "ok"
    finally:
        server.shutdown()
        server.server_close()


def test_schedule_http_routes(tmp_path: Path):
    api = _api(tmp_path)
    api.schedule_service = DataSourceScheduleService(
        store=DataSourceScheduleStore(
            tmp_path / "schedules.sqlite",
            now=lambda: datetime(2026, 5, 18, 9, 0, 0),
        ),
        server_config=api.config,
        submit_job=api.submit_job,
        get_job=api.job,
        now=lambda: datetime(2026, 5, 18, 9, 0, 0),
    )
    server = _server_for_api(api)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, _, options = _json_request(base_url, "/api/data/schedule-options")
        _, _, created = _json_request(
            base_url,
            "/api/data/schedules",
            method="POST",
            payload={
                "name": "server-schedule",
                "trigger": {"type": "once", "run_at": "2026-05-18T09:00:00+08:00"},
                "job": {
                    "source_id": "a_share",
                    "symbols": ["000001.SZ"],
                    "frequencies": ["1d"],
                    "date_range": {
                        "type": "fixed",
                        "start_date": "2025-01-01",
                        "end_date": "2025-01-02",
                    },
                },
            },
        )
        _, _, schedules = _json_request(base_url, "/api/data/schedules")
        _, _, enabled = _json_request(
            base_url,
            f"/api/data/schedules/{created['schedule_id']}/enable",
            method="POST",
        )
        _, _, updated = _json_request(
            base_url,
            f"/api/data/schedules/{created['schedule_id']}",
            method="PATCH",
            payload={"job": {"symbols": ["000002.SZ"]}},
        )
        _, _, job = _json_request(
            base_url,
            f"/api/data/schedules/{created['schedule_id']}/run-now",
            method="POST",
        )
        _, _, runs = _json_request(
            base_url,
            f"/api/data/schedules/{created['schedule_id']}/runs",
        )
        _, _, disabled = _json_request(
            base_url,
            f"/api/data/schedules/{created['schedule_id']}/disable",
            method="POST",
        )

        assert "interval" in options["trigger_types"]
        assert "start_at" in options["example"]["trigger"]
        assert options["example"]["job"]["refresh_existing"] is True
        assert schedules["schedules"][0]["schedule_id"] == created["schedule_id"]
        assert enabled["enabled"] is True
        assert updated["config"]["job"]["symbols"] == ["000002.SZ"]
        assert job["status"] == "success"
        assert runs["runs"][0]["status"] == "submitted"
        assert disabled["enabled"] is False
    finally:
        server.shutdown()
        server.server_close()


def test_schedule_delete_and_invalid_route_errors(tmp_path: Path):
    api = _api(tmp_path)
    api.schedule_service = DataSourceScheduleService(
        store=DataSourceScheduleStore(tmp_path / "schedules.sqlite"),
        server_config=api.config,
        submit_job=api.submit_job,
        get_job=api.job,
    )
    server = _server_for_api(api)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, _, created = _json_request(
            base_url,
            "/api/data/schedules",
            method="POST",
            payload={
                "name": "delete-me",
                "trigger": {"type": "once", "run_at": "2026-05-18T09:00:00+08:00"},
                "job": {
                    "source_id": "a_share",
                    "symbols": ["000001.SZ"],
                    "frequencies": ["1d"],
                    "date_range": {
                        "type": "fixed",
                        "start_date": "2025-01-01",
                        "end_date": "2025-01-02",
                    },
                },
            },
        )
        _, _, deleted = _json_request(
            base_url,
            f"/api/data/schedules/{created['schedule_id']}",
            method="DELETE",
        )
        assert deleted == {"deleted": created["schedule_id"]}

        try:
            _json_request(base_url, f"/api/data/schedules/{created['schedule_id']}")
        except HTTPError as exc:
            assert exc.code == 400
            assert "Unknown schedule" in json.loads(exc.read().decode("utf-8"))["error"]
        else:
            raise AssertionError("expected HTTPError")
    finally:
        server.shutdown()
        server.server_close()
