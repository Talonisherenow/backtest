# Data Source HTTP API

Base URL comes from the configured runtime API client, `BACKTEST_DATA_API_BASE_URL`, or explicit user/operator configuration. Use `access-discovery.md` only when establishing or diagnosing API access.

All requests use the bearer token from the configured runtime API client or `BACKTEST_DATA_API_TOKEN`:

```text
Authorization: Bearer <configured token>
```

Never print the token in chat.

The API contract is independent of transport. The current server may reach a home/local backtest service through frp, Nginx, localhost forwarding, a private route, or another controlled path; callers should treat only the discovered `base_url` as the contract.

## Read Endpoints

```text
GET /api/health
GET /api/data-sources
GET /api/kline/manifest
GET /api/kline/bars?source_id=<source_id>&symbol=<symbol>&frequency=<frequency>&adjust=<adjust>&limit=<n>&anchor=latest
GET /api/data/tasks/summary?source_id=<source_id>
GET /api/data/tasks?source_id=<source_id>&page=<n>&page_size=<n>&symbol=<partial>&frequency=<f>&status=<s>
GET /api/data/inventory?source_id=<source_id>
GET /api/data/jobs
GET /api/data/jobs/<job_id>
GET /api/data/schedule-options
GET /api/data/schedules
GET /api/data/schedules/<schedule_id>
GET /api/data/schedules/<schedule_id>/runs
```

`/api/data/tasks` is paginated. Use `/api/data/tasks/summary` for status and
frequency totals. `frequency` and `status` can be repeated to express
multi-select filters.

## Submit Job

```text
POST /api/data/jobs
Content-Type: application/json
```

Body:

```json
{
  "name": "crypto-bitget-core",
  "source": "ccxt",
  "exchange": "bitget",
  "symbols": ["BTC/USDT", "ETH/USDT"],
  "frequencies": ["1d", "4h"],
  "adjust": "none",
  "start_date": "<computed start_date>",
  "end_date": "<computed end_date>",
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

Paths are server-side paths on the data-source machine.

## Retry Failed

```text
POST /api/data/retry-failed
Content-Type: application/json
```

Body:

```json
{"source_id":"bitget"}
```

## Schedule Management

Use schedules when the user wants the data-source backend to submit existing
data crawl jobs at future times or repeated intervals. Schedule writes require
explicit confirmation.

Read endpoints:

```text
GET /api/data/schedule-options
GET /api/data/schedules
GET /api/data/schedules/<schedule_id>
GET /api/data/schedules/<schedule_id>/runs
```

Write endpoints:

```text
POST   /api/data/schedules
PATCH  /api/data/schedules/<schedule_id>
DELETE /api/data/schedules/<schedule_id>
POST   /api/data/schedules/<schedule_id>/enable
POST   /api/data/schedules/<schedule_id>/disable
POST   /api/data/schedules/<schedule_id>/run-now
```

Call `GET /api/data/schedule-options` before constructing a schedule when source
defaults, frequencies, trigger types, repeat modes, or date range types are
unknown.

Schedule body example:

```json
{
  "name": "bitget-hourly",
  "enabled": false,
  "trigger": {
    "type": "interval",
    "every": 1,
    "unit": "hours",
    "timezone": "Asia/Shanghai"
  },
  "repeat": {"mode": "count", "count": 24},
  "job": {
    "source_id": "bitget",
    "symbols": ["BTC/USDT", "ETH/USDT"],
    "frequencies": ["1h"],
    "date_range": {"type": "last_n_days", "days": 7}
  },
  "overlap_policy": "skip"
}
```

The schedule `job` template uses `source_id`; the backend maps that source to
server-side paths and provider defaults. Do not ask IM users for server paths
unless they explicitly need a one-shot `/api/data/jobs` payload override.

## Status Meaning

Job status can be `submitted`, `running`, `success`, or `failed`.

Crawl task status can include `pending`, `running`, `retrying`, `success`, or `failed`.

Schedule status can be `enabled`, `disabled`, `completed`, or `error`. Schedule
run status can be `submitted`, `skipped`, or `failed`.
