# Strategy Results Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace static strategy-result HTML generation as the main workflow with a local service that serves a dynamic strategy results catalog and on-demand detail pages.

**Architecture:** Add a `StrategyResultsService` for discovering result data and building account/drilldown payloads on demand, plus a small `ThreadingHTTPServer` wrapper for API and page routes. Keep existing viewer renderers as detail-page building blocks, but serve their HTML over HTTP instead of writing one file per result.

**Tech Stack:** Python, pandas, stdlib `http.server`, static HTML/CSS/JavaScript, pytest, Typer.

---

## File Structure

- Create `backtest/charts/strategy_results_service.py`: discover summary files, map runtime case ids to result directories, build catalog/account/drilldown payloads.
- Create `backtest/charts/strategy_results_server.py`: serve `/strategy-results`, JSON APIs, dynamic account pages, and dynamic drilldown pages.
- Modify `backtest/charts/strategy_results_catalog.py`: support dynamic app shell mode using `fetch("/api/strategy-results")`.
- Modify `backtest/cli/chart.py`: add `serve-results` command and de-emphasize static generation.
- Modify `tests/charts/test_strategy_results_catalog.py`: add dynamic app shell test.
- Create `tests/charts/test_strategy_results_service.py`: service catalog/account/drilldown tests.
- Modify `tests/test_cli_commands.py`: replace static generation CLI expectation with `serve-results` CLI expectation.
- Remove generated bulk HTML artifacts under `runs/charts/strategy_account_viewer_signal_*_hold_*.html` and `runs/charts/strategy_order_drilldown_signal_*_hold_*.html`.

## Tasks

- [x] Update design/spec documents for service mode.
- [x] Add failing tests for dynamic catalog shell, result service, and `serve-results` CLI.
- [x] Implement `StrategyResultsService`.
- [x] Implement dynamic catalog fetch mode.
- [x] Implement `serve_strategy_results` HTTP server.
- [x] Add `backtest chart serve-results`.
- [x] Remove bulk generated account/drilldown HTML artifacts.
- [x] Run focused tests and chart regression tests.
