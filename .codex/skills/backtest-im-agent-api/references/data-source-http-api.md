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
GET /api/kline/symbols?source_id=<source_id>&limit=<n>&offset=<n>&q=<query>
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
GET /api/instruments?source_id=<source_id>&q=<query>&tag=<tag_id>&limit=<n>&offset=<n>
GET /api/instruments/<instrument_id>?source_id=<source_id>
GET /api/instrument-tags?source_id=<source_id>
GET /api/instrument-tags/<tag_id>/members?source_id=<source_id>
GET /api/instrument-sources
GET /api/instrument-sync/schedules
GET /api/instrument-sync/schedules/<schedule_id>
GET /api/instrument-sync/schedules/<schedule_id>/runs
```

`/api/data/tasks` is paginated. Use `/api/data/tasks/summary` for status and
frequency totals. `frequency` and `status` can be repeated to express
multi-select filters.

`/api/kline/symbols` lists symbols that already have cached bars for a source.
It is not the instrument catalog; use `/api/instruments` for cataloged symbols
and `/api/instrument-sources` for how that catalog is refreshed.

Latest K-line semantics:

- `/api/kline/bars` returns cached bars. For crypto CCXT-backed data, the cache
  normally contains completed candles only; the current open candle may be
  absent even when the exchange can return a partial candle.
- Bar timestamps represent interval start/open time. A Beijing `17:00` `1h`
  bar covers `17:00-18:00`, and a Beijing `16:00` `4h` bar covers `16:00-20:00`.
- When a user asks why the newest bar is missing, first determine whether the
  expected bar is still open. If it is open, explain the closed-candle policy.
  If it should already be closed, then inspect schedule runs, jobs, and crawl
  tasks before calling it a crawler failure.

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
  "refresh_existing": false,
  "retry": {
    "max_attempts": 5,
    "request_delay_seconds": 0.5,
    "failure_cooldown_seconds": 30,
    "continue_on_error": true
  }
}
```

Paths are server-side paths on the data-source machine.
For one-shot jobs, `refresh_existing=false` means missing ranges only; set it to
`true` when the user explicitly wants to refresh an already cached date range.

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
    "start_at": "2026-05-20T09:00:00+08:00",
    "timezone": "Asia/Shanghai",
    "execution_delay_seconds": 60
  },
  "repeat": {"mode": "count", "count": 24},
  "job": {
    "source_id": "bitget",
    "symbols": ["BTC/USDT", "ETH/USDT"],
    "frequencies": ["1h"],
    "date_range": {
      "type": "last_n_days",
      "lookback_value": 7,
      "lookback_unit": "days"
    },
    "refresh_existing": true,
    "page_delay_seconds": 0
  },
  "overlap_policy": "skip"
}
```

Instrument-backed target example:

```json
{
  "name": "watchlist-hourly",
  "enabled": false,
  "trigger": {"type": "interval", "every": 1, "unit": "hours", "timezone": "Asia/Shanghai"},
  "repeat": {"mode": "forever"},
  "job": {
    "source_id": "bitget",
    "target": {"mode": "tag", "tag_id": "watchlist", "resolution": "dynamic"},
    "frequencies": ["1h"],
    "date_range": {"type": "last_n_days", "lookback_value": 7, "lookback_unit": "days"},
    "refresh_existing": true
  },
  "overlap_policy": "skip"
}
```

For selected instruments, use `{"mode":"symbols","instrument_ids":[...]}`.
Do not put `instrument_id` values into `job.symbols`; the backend resolves
provider symbols from instrument records.

`start_at` is optional for `interval`, `daily`, and `weekly` triggers. When it is
set, the backend will not submit the first scheduled crawl before that concrete
time; for `daily` and `weekly`, the first run is the first configured wall-clock
slot at or after `start_at`.

`trigger.unit` for interval schedules may be `seconds`, `minutes`, `hours`, or
`days` when the updated data-source server is deployed. The scheduler poll
interval defaults to one second.

`trigger.execution_delay_seconds` delays submission after the scheduled anchor.
For example, a 10:00 trigger with 60 seconds of execution delay submits at 10:01.
Relative crawl ranges are still anchored to the original scheduled time.

For recurring intraday ranges, use `date_range.type=last_n_days` with
`lookback_value` and `lookback_unit=minutes|hours|days`. UI labels such as
`Last N mins` and `Last N hours` are friendly names for this same API shape, not
separate `type` values.

`job.page_delay_seconds` is provider request throttling inside the crawl job. It
does not delay schedule execution.

`job.refresh_existing` defaults to `true` for schedules. Keep it true for
intraday recurring refreshes such as BTC/USDT 1h so each scheduled run creates a
fresh crawl task even when the date is already present in the catalog. Set it to
`false` only for missing-range backfills.

The schedule `job` template uses `source_id`; the backend maps that source to
server-side paths and provider defaults. Do not ask IM users for server paths
unless they explicitly need a one-shot `/api/data/jobs` payload override.

Compatibility check: if `GET /api/data/schedule-options` does not include
`execution_delay_units`, or a create/update response omits
`config.trigger.execution_delay_seconds` after the caller sent it, the API server
is older than this contract. Do not tell the user the execution delay was saved;
ask an operator to deploy/restart the updated data-source service.

## Instrument And Source Sync APIs

Read `instrument-api.md` for detailed instrument flows.

Instrument source sync refreshes instrument catalogs/lists. It is separate from
data crawl schedules:

```text
GET  /api/instrument-sources
POST /api/instrument-sync/run
GET  /api/instrument-sync/schedules
POST /api/instrument-sync/schedules
POST /api/instrument-sync/schedules/<schedule_id>/run-now
```

`GET /api/instrument-sources` returns each source's `provider_type`:

- `ccxt` — live exchange markets (for example Bitget via `provider_config.exchange`)
- `akshare` — live A-share instrument universe over the network
- `universe_csv` — local A-share CSV import (`provider_config.path`)

Changing A-share between live `akshare` and local `universe_csv` is a
data-source process startup/deploy setting (`--a-share-catalog-source`), not an
HTTP API. If `provider_type` is wrong for the user's intent, hand off to a
data-source operator; do not invent a local workaround.

## Status Meaning

Job status can be `submitted`, `running`, `success`, or `failed`.

Crawl task status can include `pending`, `running`, `retrying`, `success`, or `failed`.

Schedule status can be `enabled`, `disabled`, `completed`, or `error`. Schedule
run status can be `submitted`, `skipped`, or `failed`.
