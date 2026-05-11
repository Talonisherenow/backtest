# Chart Workbench Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve the K-line viewer and Strategy Results viewer from one local process.

**Architecture:** Add a small workbench HTTP server that composes the existing `KlineCacheService` and `StrategyResultsService` without changing their payload contracts. Keep existing standalone `serve` and `serve-results` commands available, and add `serve-workbench` as the preferred combined entrypoint.

**Tech Stack:** Python stdlib `http.server`, Typer, pandas-backed chart services, pytest.

---

## File Structure

- Create `backtest/charts/workbench_server.py`: one `ThreadingHTTPServer` handler for `/`, `/kline`, `/strategy-results`, and both API groups.
- Modify `backtest/cli/chart.py`: add `serve-workbench`, reusing the same K-line source construction as `serve`.
- Create `tests/charts/test_workbench_server.py`: unit-style handler smoke tests for workbench shell rendering.
- Modify `tests/test_cli_commands.py`: verify `serve-workbench` passes K-line sources, result roots, host, port, and window size.

## Tasks

- [x] Add failing tests for workbench shell and CLI delegation.
- [x] Implement `serve_chart_workbench`.
- [x] Add `backtest chart serve-workbench`.
- [x] Run focused tests.
- [x] Run chart/CLI regression tests.
- [x] Start one combined service and verify K-line plus Strategy Results APIs.
