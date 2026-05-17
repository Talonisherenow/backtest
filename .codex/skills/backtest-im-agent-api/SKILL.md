---
name: backtest-im-agent-api
description: Use when a server-side IM agent must answer backtest data-source requests by calling the data-source HTTP API, including health, sources, K-line data, crawl jobs, task status, inventory, and retry actions.
---

# Backtest IM Agent API

## Purpose

Support IM conversations by calling the backtest data-source HTTP API only.

## Hard Boundary

Never SSH, execute shell commands, edit Nginx, edit frp, inspect system logs, restart services, or read/write server files. If users ask for operations work, explain this boundary and offer API-level checks.

## Allowed API Surface

Read `references/data-source-http-api.md` before constructing requests.

Allowed without confirmation:

- `GET /api/health`
- `GET /api/data-sources`
- `GET /api/kline/manifest`
- `GET /api/kline/bars`
- `GET /api/data/tasks`
- `GET /api/data/inventory`
- `GET /api/data/jobs`
- `GET /api/data/jobs/<job_id>`

Allowed only after user confirmation:

- `POST /api/data/jobs`
- `POST /api/data/retry-failed`

## Conversation Flow

Read `references/dialogue-flows.md` when the user asks to fetch data, submit jobs, retry failures, or perform operations work.

Do not print bearer tokens. Report authorization failures without exposing token values.
