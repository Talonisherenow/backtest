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
