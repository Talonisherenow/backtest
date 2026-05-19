# IM Dialogue Flows

## Data Fetch

User intent examples: "拉数据", "补数据", "同步 BTC", "获取 A 股日线".

Flow:

1. Ensure an API client is configured. Run access discovery only if the client is missing, unvalidated, changed, or currently failing.
2. Identify market, symbols, source, exchange, date range, frequencies, adjust mode, and execution intent.
3. Fill defaults where safe.
4. Ask one concise follow-up if a required field remains ambiguous.
5. Show the final job payload summary.
6. Call `POST /api/data/jobs` only after the user confirms.
7. Return `job_id`, initial status, and the next status-check action.

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

1. Ensure an API client is configured. Run access discovery only if the client is missing, unvalidated, changed, or currently failing.
2. Confirm `source_id`.
3. Show that retry will enqueue existing failed crawl tasks for that source.
4. Call `POST /api/data/retry-failed` only after confirmation.
5. Report queued count and task ids.

## Schedule Management

User intent examples: "每小时帮我补 BTC 数据", "创建一个定时任务", "打开这个任务",
"关闭这个周期任务", "执行 24 次后停止".

Flow:

1. Ensure an API client is configured. Run access discovery only if the client is missing, unvalidated, changed, or currently failing.
2. Call `GET /api/data/schedule-options` when supported fields, source defaults, frequencies, trigger types, repeat modes, or date range types are unknown.
3. Identify trigger time, optional concrete `start_at`, repeat policy, symbols, frequencies, source, date range, `refresh_existing`, retry policy, overlap policy, and whether the schedule should start enabled.
4. Fill defaults where safe: `timezone=Asia/Shanghai`, `enabled=false` for newly created schedules, and `overlap_policy=skip`.
5. Ask one concise follow-up if a required field remains ambiguous.
6. Show the final schedule summary, including trigger, start time when provided, repeat count or stop condition, source, symbols, frequencies, date range, refresh policy, retry policy, overlap policy, and enabled state.
7. Call schedule write endpoints only after explicit confirmation.
8. Return `schedule_id`, enabled state, `next_run_at`, and the next status-check action.

For enable, disable, delete, and run-now requests, confirm the target schedule id
or exact schedule name before writing. `run-now` submits a normal data job
through the existing job path; after it returns, use `/api/data/jobs/<job_id>`
for job execution status.

## Read Requests

For health, source list, K-line, job, schedule, task, or inventory questions, call the narrowest read endpoint through the configured API client. Use `/api/data/tasks/summary` for totals and paginated `/api/data/tasks` for rows. Run access discovery only when the user asks for a connectivity check or the direct call fails with configuration, authorization, base URL, or forwarding symptoms.

If the user asks why a task is stuck or whether a crawler is still running, first read job/task state through the API. Do not inspect processes or logs from IM. If the API state is ambiguous, report the ambiguity and hand off process/log verification to a data-source operator.

## Operations Requests

If the user asks to SSH, restart services, edit Nginx, edit frp, inspect logs, run local crawlers, write scripts, query SQLite, or change system service files, say the IM agent is limited to discovering and calling the data-source HTTP API from its current runtime. Offer API access discovery and read-only API checks instead.
