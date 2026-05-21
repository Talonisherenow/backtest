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
- The data-source details open as a top drawer with primary tabs for
  `Schedules` and `Crawl Tasks`, so schedule status and task rows do not compete
  in one long panel.
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
- Enable and disable are mutating actions; the UI should highlight the action
  state and ask for confirmation before calling the API.
- The schedule and recent-run tables should have their own pagination controls,
  independent of crawl-task pagination.
- Schedule rows, schedule runs, and crawl-task rows should show the crawl data
  range when the API provides it.
- Within a source tab, the task table should support server-side pagination,
  symbol search, frequency multi-select, and status multi-select. `last_error`
  is display-only.
- The schedule editor uses one native `datetime-local` control for `start_at`
  and `run_at`, with second precision where the browser supports it. Do not
  split start time into separate date and time text inputs.
- Interval schedules support seconds, minutes, hours, and days. The data-source
  scheduler default poll interval is one second, so second-level schedule times
  require the updated backend to be running.
- `trigger.execution_delay_seconds` means "submit after the scheduled anchor",
  such as 10:00 plus a 60-second execution delay submitting at 10:01. It is
  different from request throttling inside a crawl job.
- `job.page_delay_seconds` should be shown as request gap/request delay seconds:
  it spaces provider page requests to reduce rate-limit pressure, not schedule
  execution time.
- The frequency picker in the schedule editor is a dropdown multi-select that
  displays the chosen values, usually offering `1d`, `4h`, `1h`, `15m`, and
  `1m` when supported by the source.
- The workbench range labels `Last N mins`, `Last N hours`, and `Last N days`
  map to the API's `job.date_range.type=last_n_days` with
  `lookback_value` plus `lookback_unit=minutes|hours|days`; do not invent
  separate API types named `last_n_minutes` or `last_n_hours`.
- Workbench display times should be `Asia/Shanghai`. For `/kline`, intraday
  bar timestamps from the API/cache are UTC interval-open times; convert them
  to `Asia/Shanghai` for the row range, summary cards, chart axes, hover
  labels, and `Jump to` input. The `Jump to` input accepts the Shanghai display
  time and converts it back to the API's UTC interval-open timestamp.
- The `/kline` HTML is generated when `serve-workbench` starts. Restart the
  workbench after changing K-line viewer server/template code before judging the
  browser output.
- Do not treat a missing current 1h or 4h candle as a crawl failure until the
  interval has closed. Crypto candle timestamps represent the interval start;
  for example, Beijing `17:00` on `1h` is the `17:00-18:00` open candle.
  The CCXT-backed provider drops incomplete current candles by default, even if
  the exchange API can return partial candles.
- If `GET /api/data/schedule-options` lacks `execution_delay_units`, or a
  successful schedule `PATCH` response does not echo
  `config.trigger.execution_delay_seconds`, the remote data-source server is
  older than the workbench UI. Report that the updated data-source API must be
  deployed/restarted before execution delay can persist.
- If the drawer shows a task stuck in `running`, ask data-source ops to compare
  metadata status with actual sync-job processes before assuming a crawl is
  still active.

If the user asks to fix data-source deployment, route to `backtest-data-source-ops`.

If the user asks from an IM-agent context, route API-only actions to `backtest-im-agent-api`.
