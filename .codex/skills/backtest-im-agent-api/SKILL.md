---
name: backtest-im-agent-api
description: Use when a server-side IM agent must answer backtest data-source, crawler, crawl task, K-line, inventory, schedule, instrument, tag/list, A-share, crypto, Bitget, Binance, or API-only market-data requests.
---

# Backtest IM Agent API

## Purpose

Support IM conversations by using a configured backtest data-source HTTP API client only. Establish the client when needed, then reuse it for normal API calls.

## Hard Boundary

Never SSH, execute shell commands, edit Nginx, edit frp, inspect system logs, restart services, read/write server files, modify repos, query SQLite directly, or run ad-hoc `akshare`, `ccxt`, Python, shell, or crawler scripts to satisfy an IM data request. If users ask for operations work, explain this boundary and offer API-level checks.

When the user mentions crawler service, crawl/fetch jobs, scheduled crawl jobs, recurring data fetch, periodic tasks, task status, inventory, K-line data, instrument lists, watchlists, source sync, A-share data, crypto data, Bitget/Binance data, symbols, or Chinese phrases such as `爬虫`, `爬取`, `数据源`, `数据任务`, `定时任务`, `周期任务`, `循环执行`, `打开任务`, `关闭任务`, `行情`, `标的`, `列表`, `自选`, or `K线`, use this skill and call the HTTP API. If an API endpoint exists, do not reproduce its behavior locally.

## API Client Availability

Read `references/access-discovery.md` when no usable API client/base URL is configured, when the user asks whether the server can reach the backtest backend, or when an API call fails with authorization/connectivity symptoms.

Do not run health probes before every API call. If the runtime already has a configured client, or this task has already validated one, call the narrowest endpoint directly and handle failures. Prefer environment variables for client configuration: `BACKTEST_DATA_API_BASE_URL` for the base URL and `BACKTEST_DATA_API_TOKEN` for the bearer token.

Do not assume the transport topology. The API may be reachable through frp, Nginx, a private network route, localhost, or another controlled forwarding path.

For Hermes Agent server/profile installation, skill refresh, `SOUL.md`, and `.env` setup, read `references/hermes-runtime.md`.

## Allowed API Surface

Read `references/data-source-http-api.md` before constructing requests.

Allowed without confirmation:

- `GET /api/health`
- `GET /api/data-sources`
- `GET /api/kline/manifest`
- `GET /api/kline/bars`
- `GET /api/data/tasks/summary`
- `GET /api/data/tasks`
- `GET /api/data/inventory`
- `GET /api/data/jobs`
- `GET /api/data/jobs/<job_id>`
- `GET /api/data/schedule-options`
- `GET /api/data/schedules`
- `GET /api/data/schedules/<schedule_id>`
- `GET /api/data/schedules/<schedule_id>/runs`
- `GET /api/instruments`
- `GET /api/instruments/<instrument_id>`
- `GET /api/instrument-tags`
- `GET /api/instrument-tags/<tag_id>/members`
- `GET /api/instrument-sources`
- `GET /api/instrument-sync/schedules`
- `GET /api/instrument-sync/schedules/<schedule_id>`
- `GET /api/instrument-sync/schedules/<schedule_id>/runs`

Allowed only after user confirmation:

- `POST /api/data/jobs`
- `POST /api/data/retry-failed`
- `POST /api/data/schedules`
- `PATCH /api/data/schedules/<schedule_id>`
- `DELETE /api/data/schedules/<schedule_id>`
- `POST /api/data/schedules/<schedule_id>/enable`
- `POST /api/data/schedules/<schedule_id>/disable`
- `POST /api/data/schedules/<schedule_id>/run-now`
- `POST /api/instruments`
- `PATCH /api/instruments/<instrument_id>`
- `DELETE /api/instruments/<instrument_id>`
- `POST /api/instrument-tags`
- `PATCH /api/instrument-tags/<tag_id>`
- `DELETE /api/instrument-tags/<tag_id>`
- `PUT /api/instrument-tags/<tag_id>/members`
- `POST /api/instrument-tags/<tag_id>/members`
- `DELETE /api/instrument-tags/<tag_id>/members/<instrument_id>`
- `POST /api/instrument-sync/run`
- `POST /api/instrument-sync/schedules`
- `PATCH /api/instrument-sync/schedules/<schedule_id>`
- `DELETE /api/instrument-sync/schedules/<schedule_id>`
- `POST /api/instrument-sync/schedules/<schedule_id>/enable`
- `POST /api/instrument-sync/schedules/<schedule_id>/disable`
- `POST /api/instrument-sync/schedules/<schedule_id>/run-now`

## Conversation Flow

Read `references/dialogue-flows.md` when the user asks to fetch data, submit jobs, retry failures, or perform operations work.

Read `references/instrument-api.md` when the user asks about instruments, symbols, tags/lists, watchlists, source catalog sync, or instrument sync schedules.

Do not print bearer tokens. Report authorization failures without exposing token values.
