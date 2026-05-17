---
name: backtest-im-agent-api
description: Use when a server-side IM agent must answer backtest data-source requests, discover whether its runtime can reach the backtest data-source HTTP API, or use API-only health, K-line, crawl job, task, inventory, and retry actions.
---

# Backtest IM Agent API

## Purpose

Support IM conversations by using a configured backtest data-source HTTP API client only. Establish the client when needed, then reuse it for normal API calls.

## Hard Boundary

Never SSH, execute shell commands, edit Nginx, edit frp, inspect system logs, restart services, or read/write server files. If users ask for operations work, explain this boundary and offer API-level checks.

## API Client Availability

Read `references/access-discovery.md` when no usable API client/base URL is configured, when the user asks whether the server can reach the backtest backend, or when an API call fails with authorization/connectivity symptoms.

Do not run health probes before every API call. If the runtime already has a configured client, or this task has already validated one, call the narrowest endpoint directly and handle failures.

Do not assume the transport topology. The API may be reachable through frp, Nginx, a private network route, localhost, or another controlled forwarding path.

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
