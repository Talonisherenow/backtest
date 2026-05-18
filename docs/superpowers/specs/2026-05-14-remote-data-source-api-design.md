# Remote Data Source API Design

Date: 2026-05-14
Status: approved for implementation planning
Branch: `feat/data-crawl-management`

## 1. Background

The current workbench can inspect K-line data through local JSON endpoints:

```text
GET /api/manifest
GET /api/bars
```

Those endpoints are embedded in `backtest.charts.kline_server` and
`backtest.charts.workbench_server`, and they read local Parquet cache files
through `KlineCacheService`.

Market data crawling is currently CLI-only:

```text
backtest data sync
backtest data sync-job
backtest data tasks
backtest data inventory
backtest data retry
```

This design extracts a first remote data-source API so a server on the same LAN
can own crawling and cached bars. A workbench opened elsewhere should connect
to that server, inspect its K-line data, submit crawl jobs, and monitor progress
without re-crawling or copying Parquet data locally.

## 2. Goals

- Expose the existing local K-line query capability as a reusable data-source
  HTTP API.
- Let the workbench connect to a remote data-source server with a configured
  base URL.
- Support remote submission of market-data sync jobs in the trusted-LAN phase.
- Support polling task/job status and cached inventory from the remote server.
- Keep the first implementation small and compatible with the current stdlib
  HTTP server style.
- Reuse existing `KlineCacheService`, `DataSyncService`, `MarketDataJobRunner`,
  `CrawlTaskManager`, and `DataCatalog` behavior instead of duplicating data
  logic.

## 3. Non-Goals

- No public Internet deployment hardening in this phase.
- No authentication, users, permissions, rate limits, or audit log in this
  phase.
- No distributed queue, worker cluster, or persistent scheduler.
- No task cancellation command.
- No WebSocket or server-sent events; status polling is sufficient.
- No automatic copying or syncing of remote Parquet files back to the local
  workstation.
- No remote strategy result storage in this phase; strategy result APIs remain
  local to the workbench process.

## 4. Architecture

Add a new data-source service boundary under `backtest/data_source/`:

```text
backtest/data_source/
  __init__.py
  api.py
  server.py
  jobs.py
  config.py
```

Responsibilities:

- `api.py`: Compose K-line, catalog, crawl-task, retry, and job-submission
  operations behind a small Python facade that is easy to test without HTTP.
- `server.py`: Translate HTTP requests to the facade and return JSON.
- `jobs.py`: Run submitted sync jobs in background threads and expose in-process
  job snapshots.
- `config.py`: Define server source roots, metadata paths, bars roots, and
  default CORS behavior.

The first server should stay with `ThreadingHTTPServer` to match current
`kline_server.py` and `workbench_server.py`. The API facade should be structured
so a future FastAPI implementation can wrap the same logic.

## 5. Data Source Server CLI

Add a new command under the existing Typer app:

```bash
backtest data-source serve \
  --bitget-bars-root data/crypto/bitget/bars \
  --bitget-metadata data/crypto/bitget/metadata.sqlite \
  --a-share-bars-root data/bars \
  --a-share-metadata data/metadata.sqlite \
  --a-share-universe data/universe/a_share_all_20260504.csv \
  --host 0.0.0.0 \
  --port 8768
```

Defaults should support the current local research layout:

```text
bitget bars: data/crypto/bitget/bars
bitget metadata: data/crypto/bitget/metadata.sqlite
a-share bars: data/bars
a-share metadata: data/metadata.sqlite
a-share universe: data/universe/a_share_all_20260504.csv
host: 127.0.0.1
port: 8768
```

LAN use should explicitly pass `--host 0.0.0.0`. The startup log should print
the bind address and a local URL. If a configured source directory is missing,
the command should fail with a clear message unless that source was disabled.

## 6. HTTP API

All responses are JSON. Errors return:

```json
{"error":"message"}
```

### 6.1 Health

```text
GET /api/health
```

Response:

```json
{
  "status": "ok",
  "service": "backtest-data-source"
}
```

### 6.2 Data Sources

```text
GET /api/data-sources
```

Response lists configured source ids and their capabilities:

```json
{
  "sources": [
    {
      "source_id": "bitget",
      "source_label": "Bitget",
      "asset_class": "crypto",
      "bars": true,
      "crawl_jobs": true
    },
    {
      "source_id": "a_share",
      "source_label": "A-share",
      "asset_class": "equity",
      "bars": true,
      "crawl_jobs": true
    }
  ]
}
```

### 6.3 K-line Manifest

```text
GET /api/kline/manifest
```

This wraps `KlineCacheService.manifest()`. The response shape should remain
compatible with the existing viewer manifest, including `sources`, `symbols`,
`frequencies`, `series`, row counts, first/last bar, adjust, and years.

### 6.4 K-line Bars

```text
GET /api/kline/bars?source_id=bitget&symbol=BTC%2FUSDT&frequency=1d&adjust=none&limit=300&anchor=latest
```

This wraps `KlineCacheService.bars()`. Supported query parameters match the
current local endpoint:

```text
source_id
symbol
frequency
adjust
limit
offset
start
anchor
```

The response shape stays compatible with the current `/api/bars` payload:

```json
{
  "source_id": "bitget",
  "source_label": "Bitget",
  "symbol": "BTC/USDT",
  "frequency": "1d",
  "adjust": "none",
  "rows": 1096,
  "loaded_rows": 300,
  "offset": 796,
  "limit": 300,
  "start_row": 797,
  "end_row": 1096,
  "first_bar": "2023-05-09",
  "last_bar": "2026-05-08",
  "bars": []
}
```

### 6.5 Crawl Tasks

```text
GET /api/data/tasks?source_id=bitget
```

Response:

```json
{
  "tasks": [
    {
      "task_id": 38,
      "symbol": "BNB/USDT",
      "frequency": "1m",
      "adjust": "none",
      "start_date": "2023-05-09",
      "end_date": "2026-05-08",
      "source": "ccxt:bitget",
      "status": "success",
      "attempts": 1,
      "last_error": null,
      "created_at": "2026-05-13T22:11:00",
      "updated_at": "2026-05-13T22:12:00"
    }
  ]
}
```

`source_id` selects the configured metadata database. The server should return
400 for unknown source ids.

### 6.6 Inventory

```text
GET /api/data/inventory?source_id=bitget
```

Response:

```json
{
  "records": [
    {
      "symbol": "BTC/USDT",
      "frequency": "1d",
      "adjust": "none",
      "source": "ccxt:bitget",
      "start_date": "2023-05-09",
      "end_date": "2026-05-08",
      "rows": 1096,
      "cache_path": "data/crypto/bitget/bars/frequency=1d/adjust=none/symbol=BTC%2FUSDT/year=2026/bars.parquet"
    }
  ]
}
```

### 6.7 Submit Data Job

```text
POST /api/data/jobs
Content-Type: application/json
```

Request:

```json
{
  "name": "crypto-bitget-core",
  "source": "ccxt",
  "exchange": "bitget",
  "symbols": ["BTC/USDT", "ETH/USDT"],
  "frequencies": ["1d", "4h"],
  "adjust": "none",
  "start_date": "2023-05-09",
  "end_date": "2026-05-08",
  "bars_root": "data/crypto/bitget/bars",
  "metadata": "data/crypto/bitget/metadata.sqlite",
  "output_dir": "runs/crypto_market_data/bitget_core",
  "page_delay_seconds": 0.35,
  "retry": {
    "max_attempts": 5,
    "request_delay_seconds": 0.5,
    "failure_cooldown_seconds": 30,
    "continue_on_error": true
  }
}
```

The server validates the payload with `DataSyncJobConfig`. For the trusted-LAN
first version, the caller may send paths, but the server should normalize them
relative to its own working directory. The server must not read local client
paths.

Response:

```json
{
  "job_id": "20260514T101530-crypto-bitget-core",
  "status": "submitted"
}
```

The HTTP request should return quickly. The actual sync runs in a background
thread.

### 6.8 Job Status

```text
GET /api/data/jobs
GET /api/data/jobs/20260514T101530-crypto-bitget-core
```

Response for one job:

```json
{
  "job_id": "20260514T101530-crypto-bitget-core",
  "name": "crypto-bitget-core",
  "status": "running",
  "submitted_at": "2026-05-14T10:15:30",
  "started_at": "2026-05-14T10:15:31",
  "finished_at": null,
  "total_items": 8,
  "success_count": 3,
  "failed_count": 0,
  "total_rows": 3288,
  "error": null
}
```

The in-process registry should expose submitted, running, success, and failed
jobs. If the server restarts, historical job process state may be lost, but
`crawl_tasks`, `inventory`, and job `summary.csv` remain available from SQLite
and output files. This is acceptable for the first version.

### 6.9 Retry Failed Tasks

```text
POST /api/data/retry-failed
Content-Type: application/json
```

Request:

```json
{"source_id":"bitget"}
```

Response:

```json
{
  "queued": 3,
  "task_ids": [5, 7, 8]
}
```

This wraps `CrawlTaskManager.failed_tasks()` and `mark_retrying()`.

## 7. Workbench Remote Data Source

The dynamic K-line viewer should support an optional `data_api_base_url` payload
field:

```json
{
  "mode": "dynamic",
  "data_api_base_url": "http://192.168.1.10:8768"
}
```

When present, the viewer should request:

```text
<base>/api/kline/manifest
<base>/api/kline/bars?source_id=bitget&symbol=BTC%2FUSDT&frequency=1d&adjust=none&limit=300
```

When absent, it should preserve current same-origin behavior:

```text
/api/manifest
/api/bars?source_id=bitget&symbol=BTC%2FUSDT&frequency=1d&adjust=none&limit=300
```

The workbench CLI should expose:

```bash
backtest chart serve-workbench \
  --data-api-base-url http://192.168.1.10:8768
```

In this mode, the local workbench still serves pages and strategy results, but
the K-line viewer reads market bars from the remote data-source server.

For the first version, the data job management UI can be minimal:

- The data-source API is the primary contract.
- The workbench may expose a simple `Data Jobs` page or panel only if it can be
  implemented without broad UI churn.
- K-line remote access is required for acceptance; polished job-management UI
  is optional for the first implementation plan.

## 8. LAN And CORS

The trusted-LAN first version should add permissive CORS headers to data-source
API responses:

```text
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, OPTIONS
Access-Control-Allow-Headers: Content-Type
```

The server should handle `OPTIONS` preflight for POST endpoints.

Security hardening will be a later design:

- API token or mTLS.
- CORS allowlist.
- Job payload restrictions.
- Audit logs.
- Per-source authorization.

## 9. Error Handling

- Unknown route: 404 JSON error.
- Bad query parameter or unknown source id: 400 JSON error.
- Malformed JSON body: 400 JSON error.
- Job submission validation failure: 400 JSON error with pydantic message.
- Background job failure: job status becomes `failed`, with `error` set.
- Missing bars for a valid symbol/frequency: preserve current
  `KlineCacheService` error message.
- CORS preflight should return 204 with CORS headers.

The first implementation should avoid leaking stack traces through HTTP.

## 10. Testing

Add focused tests before implementation:

- Data-source API facade returns K-line manifest and bars from fixture Parquet
  roots.
- HTTP server serves `/api/kline/manifest` and `/api/kline/bars` with the new
  paths and existing payload shapes.
- HTTP server lists crawl tasks and inventory from fixture SQLite metadata.
- POST `/api/data/jobs` validates payloads, returns a job id, and starts a
  background runner through an injectable fake runner.
- GET `/api/data/jobs/<job_id>` returns submitted/running/success/failed
  snapshots.
- POST `/api/data/retry-failed` marks failed tasks retrying.
- K-line viewer supports `data_api_base_url` while preserving same-origin
  default fetches.
- `backtest chart serve-workbench --data-api-base-url http://192.168.1.10:8768`
  passes the base URL into the K-line viewer payload.
- Data-source CLI passes host, port, bars roots, metadata paths, and universe
  path into the server.

Existing chart and data tests should keep passing.

## 11. Acceptance Criteria

- Start a data-source server on a LAN host:

```bash
backtest data-source serve --host 0.0.0.0 --port 8768
```

- From another machine, open:

```text
http://<server-ip>:8768/api/kline/manifest
```

and receive the server's cached data manifest.

- Start local workbench with:

```bash
backtest chart serve-workbench \
  --data-api-base-url http://<server-ip>:8768 \
  --host 127.0.0.1 \
  --port 8767
```

- Open `http://127.0.0.1:8767/kline` and browse server-side K-line data without
  local Parquet copies.
- Submit a data job through `POST /api/data/jobs` and receive a `job_id`.
- Poll `GET /api/data/jobs/<job_id>` and `GET /api/data/tasks?source_id=bitget` to
  observe progress.
- Inspect `GET /api/data/inventory?source_id=bitget` after the job writes data.

## 12. Future Work

- Authentication and CORS allowlist for non-LAN deployment.
- Persistent job registry that survives server restarts.
- Task cancellation and pause/resume.
- Job templates stored server-side so clients submit a template id plus
  overrides instead of raw paths.
- Workbench data job management UI with submit form, progress table, and retry
  actions.
- Remote strategy result service for browsing backtest results stored on the
  same server as market data.
