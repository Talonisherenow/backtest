# Data Job Fields

Use this reference when a user asks to get, fetch, download, crawl, sync, or backfill market data.

Before running or submitting a job, show a proposal that includes:

- market or asset class
- symbols or symbol source
- source
- exchange when `source=ccxt`
- concrete `start_date` and `end_date`
- frequencies
- adjust mode
- server-side `bars_root`
- server-side `metadata`
- server-side `output_dir`
- whether the operation will only prepare config or actually execute

Defaults:

- date range: most recent one year ending on today's local date
- crypto: `source=ccxt`, `adjust=none`, `frequencies=[1d, 4h, 1h, 30m, 15m, 5m, 1m]`
- A-share: `source=akshare`, `adjust=qfq`, `frequencies=[1d]`

For crypto, confirm `exchange`. If the user did not name one, infer it only from an existing repo default or ask.

For A-share, do not use crypto intraday frequencies. AkShare currently accepts daily bars.

For scheduled data jobs, also confirm:

- trigger type: `once`, `interval`, `daily`, or `weekly`
- concrete trigger time or interval and `timezone`
- repeat policy: `forever`, `count`, or `until`
- whether the schedule should start enabled
- `overlap_policy`, defaulting to `skip`
- date range mode inside the job template, usually `last_n_days` for recurring refreshes

Schedule job templates use `source_id` and let the data-source backend map
server-side paths and provider defaults. Prefer `GET /api/data/schedule-options`
before creating or updating schedules.
