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
- verify K-line and strategy-results pages

Not allowed:

- editing Nginx, frp, LaunchAgent, or system service files
- exposing local workbench publicly when the HTML includes a data API token

## Workflow

Read `references/workbench-runbook.md` for local and remote startup commands.

If the user asks to fix data-source deployment, route to `backtest-data-source-ops`.

If the user asks from an IM-agent context, route API-only actions to `backtest-im-agent-api`.
