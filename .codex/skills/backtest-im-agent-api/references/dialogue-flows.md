# IM Dialogue Flows

## Data Fetch

User intent examples: "拉数据", "补数据", "同步 BTC", "获取 A 股日线".

Flow:

1. Identify market, symbols, source, exchange, date range, frequencies, adjust mode, and execution intent.
2. Fill defaults where safe.
3. Ask one concise follow-up if a required field remains ambiguous.
4. Show the final job payload summary.
5. Call `POST /api/data/jobs` only after the user confirms.
6. Return `job_id`, initial status, and the next status-check action.

Required proposal fields:

- market or asset class
- symbols or symbol source
- source and exchange when `source=ccxt`
- concrete `start_date` and `end_date`
- frequencies
- adjust mode
- server-side `bars_root`
- server-side `metadata`
- server-side `output_dir`

Defaults:

- date range: most recent one year ending on today's local date
- crypto: `source=ccxt`, `adjust=none`, `frequencies=[1d, 4h, 1h, 30m, 15m, 5m, 1m]`
- A-share: `source=akshare`, `adjust=qfq`, `frequencies=[1d]`

## Retry Failed Tasks

Flow:

1. Confirm `source_id`.
2. Show that retry will enqueue existing failed crawl tasks for that source.
3. Call `POST /api/data/retry-failed` only after confirmation.
4. Report queued count and task ids.

## Operations Requests

If the user asks to SSH, restart services, edit Nginx, edit frp, inspect logs, or change system service files, say the IM agent is limited to the data-source HTTP API. Offer `GET /api/health`, `GET /api/data-sources`, `GET /api/data/jobs`, or `GET /api/data/tasks` checks instead.
