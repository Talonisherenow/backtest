---
name: backtest-data-source-ops
description: Use when operating a backtest data-source machine or its VPS exposure, including data-source processes, frpc/frps, Nginx, crawl jobs, crawl task status, inventory, retries, ports, logs, and deployment verification.
---

# Backtest Data Source Ops

## Purpose

Operate the machine and infrastructure that owns cached market data, crawl tasks, and the public data-source API.

## First Checks

Confirm repo shape:

```bash
uv run backtest data-source serve --help
uv run backtest data sync-job --help
rg -n "data-source serve|frpc|frps|nginx|api/data/jobs" docs deploy .codex/skills
```

## Authority

Allowed:

- start and inspect `backtest data-source serve`
- inspect and maintain frpc/frps/Nginx deployment
- inspect logs, ports, and launch services
- submit, inspect, and retry crawl jobs after confirmation

Not the right skill for:

- local workbench UI setup; use `backtest-workbench-ops`
- IM-only API conversations; use `backtest-im-agent-api`

## Workflows

For deployment and process work, read `references/deployment-runbook.md`.

For data fetch, crawl, sync, backfill, retry, and job field confirmation, read `references/data-job-fields.md` before acting.

## Verification

Use the narrowest checks that match the user's request:

```bash
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" http://127.0.0.1:8768/api/health
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" http://127.0.0.1:8768/api/data-sources
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" "http://127.0.0.1:8768/api/data/tasks/summary?source_id=bitget"
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" "http://127.0.0.1:8768/api/data/tasks?source_id=bitget&page=1&page_size=50&symbol=BTC&frequency=1d&status=success"
uv run backtest data tasks --metadata data/crypto/bitget/metadata.sqlite
uv run backtest data inventory --metadata data/crypto/bitget/metadata.sqlite
```

Task status API notes:

- `/api/data/tasks/summary?source_id=<source_id>` returns lightweight total,
  status counts, frequency counts, and latest update time. Use it for workbench
  monitor totals instead of loading every task.
- `/api/data/tasks` is paginated. It accepts `page`, `page_size`, optional
  `symbol` partial search, repeated `frequency` filters, and repeated `status`
  filters.
- If a task is shown as `running`, confirm there is a real `backtest data
  sync-job` process or data-source in-process job before treating it as active.
  Interrupted sync processes can leave stale `running` rows in metadata.

For public exposure, verify the chain in order: source loopback, VPS loopback, public HTTPS.
