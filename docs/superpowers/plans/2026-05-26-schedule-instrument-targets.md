# Schedule Instrument Targets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make data-source schedules choose crawl targets from existing instruments or instrument Lists instead of free-form symbols.

**Architecture:** Add optional `job.target` to schedule configs and inject an instrument-aware resolver into `DataSourceScheduleService`. Keep legacy `job.symbols` working, add tag member read API, and update the workbench schedule editor to choose source and targets through API-backed controls.

**Tech Stack:** Python, Pydantic models, stdlib HTTP server, SQLite metadata store, vanilla HTML/CSS/JavaScript workbench, pytest.

---

## Task 1: Backend Target Contract

**Files:**
- Modify: `backtest/data_source/schedules.py`
- Test: `tests/data_source/test_api.py`

- [ ] Add `ScheduleTargetConfig` with `mode=symbols|tag`, `instrument_ids`, `tag_id`, and `resolution=dynamic`.
- [ ] Change `ScheduleJobTemplate.symbols` to default to an empty list, and require either `symbols` or `target`.
- [ ] Add a resolver callback to `DataSourceScheduleService`.
- [ ] Update `build_job_payload()` to use resolved target symbols when `job.target` exists.
- [ ] Verify legacy `job.symbols` schedules still create and run.

## Task 2: Instrument Tag Member API

**Files:**
- Modify: `backtest/data_source/api.py`
- Modify: `backtest/data_source/server.py`
- Test: `tests/data_source/test_server.py`

- [ ] Add `DataSourceApi.instrument_tag_members(tag_id, source_id=None)`.
- [ ] Expose `GET /api/instrument-tags/<tag_id>/members?source_id=<source_id>`.
- [ ] Ensure source filtering rejects mismatched instruments.
- [ ] Verify the endpoint returns tag metadata and members.

## Task 3: Schedule Target Resolver

**Files:**
- Modify: `backtest/data_source/api.py`
- Modify: `backtest/data_source/schedules.py`
- Test: `tests/data_source/test_api.py`

- [ ] Add `_resolve_schedule_symbols(source_id, target, fallback_symbols)`.
- [ ] Resolve `mode=symbols` from instrument IDs to provider symbols.
- [ ] Resolve `mode=tag` from List/tag members to provider symbols.
- [ ] Reject empty targets, unknown instruments, unknown tags, and source mismatches.
- [ ] Verify dynamic List behavior by changing tag membership before `run_now`.

## Task 4: Workbench Schedule Editor

**Files:**
- Modify: `backtest/charts/workbench_server.py`
- Test: `tests/charts/test_workbench_server.py`

- [ ] Replace `scheduleEditSourceId` text input with a select populated from data sources.
- [ ] Replace `scheduleEditSymbols` text input with target mode controls.
- [ ] Add instrument search against `/api/instruments`.
- [ ] Add List selection and member preview against `/api/instrument-tags` and `/api/instrument-tags/<tag_id>/members`.
- [ ] Build `job.target` on save and keep legacy symbols display for old schedules.
- [ ] Render schedule rows with either explicit symbols or List summary.

## Task 5: Verification

**Files:**
- Existing tests only.

- [ ] Run `uv run pytest tests/data_source/test_api.py tests/data_source/test_server.py tests/charts/test_workbench_server.py -q`.
- [ ] Run `git diff --check`.
- [ ] Restart workbench and verify the editor loads with the new Source and Symbols controls.
