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

Closed candle policy:

- Crypto CCXT jobs use closed candles by default. The provider drops the current
  incomplete candle (`drop_incomplete=true`) even when an exchange endpoint can
  return a partial bar.
- A bar timestamp is the interval start/open time, not the time at which the bar
  becomes final. Beijing `17:00` on `1h` means the `17:00-18:00` candle; Beijing
  `16:00` on `4h` means the `16:00-20:00` candle.
- If the latest expected candle is still open, a successful crawl that stops at
  the previous closed bar is normal. Do not retry or restart the crawler solely
  for that gap.

For crypto, confirm `exchange`. If the user did not name one, infer it only from an existing repo default or ask.

For A-share, do not use crypto intraday frequencies. AkShare currently accepts daily bars.

For scheduled data jobs, also confirm:

- trigger type: `once`, `interval`, `daily`, or `weekly`
- concrete trigger time or interval and `timezone`; interval schedules may use
  `seconds`, `minutes`, `hours`, or `days`
- optional concrete `start_at`; for `daily` and `weekly`, this is the earliest
  wall-clock boundary and the first run will be the first matching slot at or
  after it
- optional `trigger.execution_delay_seconds`, meaning the data-source submits
  after the scheduled anchor, such as 10:00 plus 60 seconds submitting at 10:01
- repeat policy: `forever`, `count`, or `until`
- whether the schedule should start enabled
- `overlap_policy`, defaulting to `skip`
- date range mode inside the job template, usually `last_n_days` for recurring
  refreshes. For intraday refreshes, use `lookback_value` plus
  `lookback_unit=minutes|hours|days`; UI labels may say `Last N mins`,
  `Last N hours`, or `Last N days`, but the API type stays `last_n_days`
- `refresh_existing`, defaulting to `true` for scheduled jobs so intraday
  refreshes create a crawl task even when the catalog already covers the date
- `job.page_delay_seconds`, if needed, as provider request spacing inside a
  crawl job. It is not schedule execution delay.

Schedule job templates use `source_id` and let the data-source backend map
server-side paths and provider defaults. Prefer `GET /api/data/schedule-options`
before creating or updating schedules.

Minimum schedule payload for the current API shape:

```json
{
  "name": "bitget-hourly",
  "enabled": false,
  "trigger": {
    "type": "interval",
    "every": 1,
    "unit": "hours",
    "start_at": "2026-05-20T10:00:00+08:00",
    "timezone": "Asia/Shanghai",
    "execution_delay_seconds": 60
  },
  "repeat": {"mode": "forever"},
  "job": {
    "source_id": "bitget",
    "symbols": ["BTC/USDT"],
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
