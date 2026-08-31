---
name: backtest-data-source-ops
description: Use when operating a backtest data-source machine or VPS exposure, including data-source processes, frpc/frps, Nginx, crawl jobs, schedules, instrument catalogs, instrument tags/lists, instrument source sync, task status, inventory, retries, ports, logs, and deployment verification.
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
- submit, inspect, schedule, enable/disable, and retry crawl jobs after confirmation
- inspect and manage instrument catalogs, tags/lists, source sync, and instrument sync schedules after confirmation

Not the right skill for:

- local workbench UI setup; use `backtest-workbench-ops`
- IM-only API conversations; use `backtest-im-agent-api`

## Workflows

For deployment and process work, read `references/deployment-runbook.md`.

For data fetch, crawl, sync, backfill, retry, and job field confirmation, read `references/data-job-fields.md` before acting.

For data crawl schedules, instrument-backed schedule targets, schedule runs, enable/disable, and run-now behavior, read `references/schedule-ops.md`.

For instrument CRUD, tags/lists, source catalog sync, and instrument sync schedules, read `references/instrument-ops.md`.

## Verification

Use the narrowest checks that match the user's request:

```bash
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" http://127.0.0.1:8768/api/health
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" http://127.0.0.1:8768/api/data-sources
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" "http://127.0.0.1:8768/api/data/tasks/summary?source_id=bitget"
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" "http://127.0.0.1:8768/api/data/tasks?source_id=bitget&page=1&page_size=50&symbol=BTC&frequency=1d&status=success"
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" http://127.0.0.1:8768/api/data/schedule-options
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" http://127.0.0.1:8768/api/data/schedules
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" http://127.0.0.1:8768/api/instrument-sources
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" "http://127.0.0.1:8768/api/instruments?source_id=bitget&limit=5"
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" "http://127.0.0.1:8768/api/instrument-tags?source_id=bitget"
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" "http://127.0.0.1:8768/api/kline/symbols?source_id=a_share&limit=5"
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" http://127.0.0.1:8768/api/instrument-sync/schedules
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
- If latest K-line data appears missing, compare the expected bar to the current
  interval before blaming the scheduler. Crypto bar timestamps are interval
  start/open times, and the CCXT-backed provider drops incomplete current
  candles by default. At Beijing `17:09`, the `17:00` 1h candle and `16:00` 4h
  candle are still open and should not be cached as complete bars yet.
- A schedule/job/task can be `success` while the current open candle is absent.
  Only diagnose crawler failure after the expected candle's interval has closed
  or after direct API/job/task evidence shows an error.

Schedule API notes:

- See `references/schedule-ops.md` for the current schedule contract, including
  instrument-backed `job.target`, dynamic tag targets, execution delay, and
  instrument sync schedules.

For public exposure, verify the chain in order: source loopback, VPS loopback, public HTTPS.
