---
name: backtest-workbench-ops
description: Use when configuring, starting, opening, or troubleshooting the backtest chart workbench, K-line viewer, strategy-results viewer, remote data API base URL, workbench token wiring, result roots, local ports, and browser verification.
---

# Backtest Workbench Ops

## Purpose

Operate the local workbench experience. The workbench may read K-line data from local bars or from a remote data-source API.

## First Checks

```bash
uv run backtest chart serve-workbench --help
rg -n "serve-workbench|data-api-base-url|BACKTEST_DATA_API_TOKEN" docs backtest .codex/skills
```

## Authority

Allowed:

- start and verify `backtest chart serve-workbench`
- configure `--data-api-base-url`
- configure `BACKTEST_DATA_API_TOKEN` or `--data-api-token`
- persist a user-provided data API token into the local shell environment for
  workbench use
- verify K-line and strategy-results pages

Not allowed:

- editing Nginx, frp, LaunchAgent, or system service files
- exposing local workbench publicly when the HTML includes a data API token

## Workflow

Read `references/workbench-runbook.md` for local and remote startup commands.

If the user provides a remote data API token for the workbench:

- Default to persisting it as `BACKTEST_DATA_API_TOKEN` in `~/.backtest-env`
  unless the user asks for one-shot/no persistence.
- Ensure `~/.zshrc` and `~/.zprofile` source `~/.backtest-env` using an
  idempotent guard, and set `chmod 600 ~/.backtest-env`.
- Do not echo the token in command output, final answers, process arguments, or
  logs. Prefer passing it through environment variables rather than
  `--data-api-token`.
- Verify with a token-safe check: confirm the workbench payload has
  `data_api_token`, and probe a narrow remote endpoint with
  `Authorization: Bearer $BACKTEST_DATA_API_TOKEN`, reporting only status/byte
  count.

When verifying the workbench home data-source monitor:

- The compact home summary should stay visible below the header when
  `--data-api-base-url` is configured.
- The crawl-task summary is backed by `/api/data/tasks/summary?source_id=<source_id>`,
  not by a full task list fetch.
- The schedule summary and drawer table are backed by `/api/data/schedules`.
- The recent schedule run table is backed by
  `/api/data/schedules/<schedule_id>/runs`; use it to verify the latest trigger
  for an active schedule rather than relying on crawl task `updated_at`.
- The `Details` drawer should provide source tabs, one tab per configured data
  source.
- The drawer should show schedules with status, trigger, repeat, next run, last
  job, and recent schedule runs before the crawl task table.
- Schedule rows expose operational controls backed by data-source HTTP APIs:
  enable/disable via `POST /api/data/schedules/<schedule_id>/enable|disable`,
  immediate execution via `POST /api/data/schedules/<schedule_id>/run-now`, and
  basic edits via `PATCH /api/data/schedules/<schedule_id>`.
- Within a source tab, the task table should support server-side pagination,
  symbol search, frequency multi-select, and status multi-select. `last_error`
  is display-only.
- If the drawer shows a task stuck in `running`, ask data-source ops to compare
  metadata status with actual sync-job processes before assuming a crawl is
  still active.

If the user asks to fix data-source deployment, route to `backtest-data-source-ops`.

If the user asks from an IM-agent context, route API-only actions to `backtest-im-agent-api`.
