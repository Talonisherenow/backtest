# Data Source Scheduler Design

Date: 2026-05-18
Status: draft for review
Branch: `codex/feat-data-source-scheduler`
Base branch note: this repository does not have a `develop` branch; this work was branched from the updated `main` branch.

## 1. Background

The data-source backend already exposes a remote HTTP API for cached K-line data,
crawl task state, inventory, one-shot crawl job submission, and retrying failed
tasks:

```text
GET  /api/data-sources
GET  /api/data/tasks/summary
GET  /api/data/tasks
GET  /api/data/jobs
GET  /api/data/jobs/<job_id>
POST /api/data/jobs
POST /api/data/retry-failed
```

`POST /api/data/jobs` validates its payload through `DataSyncJobConfig`, then
submits work to `DataSourceJobRegistry`, which runs `MarketDataJobRunner` in a
background thread. This is the right execution path for data crawling and should
remain the only path that actually starts crawl jobs.

The missing capability is a remote management layer for recurring submissions.
An operator or IM Agent should be able to say things such as:

- run this crawl job every hour starting at 09:00
- run it 24 times, then stop
- enable or disable the schedule
- update symbols, K-line frequencies, retry policy, or trigger time
- run the configured schedule immediately once

The scheduler must make these operations available through the data-source HTTP
API and must expose enough metadata for an AI agent to fill valid request
payloads without guessing server-side paths or enum values.

## 2. Goals

- Add a persistent, HTTP-managed scheduler to the data-source backend.
- Reuse the existing data job submission path instead of adding a second crawl
  runner.
- Support schedule creation, listing, detail, update, delete, enable, disable,
  and manual run-now.
- Support execution time, interval-based repetition, daily/weekly wall-clock
  schedules, finite run counts, run-until timestamps, and forever schedules.
- Support AI-friendly field discovery through a schedule options endpoint.
- Let schedules store a data job template that compiles into the existing
  `POST /api/data/jobs` payload at trigger time.
- Keep implementation dependency-light and consistent with the current stdlib
  HTTP server style.
- Preserve existing bearer-token authorization behavior for all schedule
  endpoints.
- Update `backtest-im-agent-api` so server-side IM agents can manage schedules
  through HTTP only.

## 3. Non-Goals

- No distributed queue or worker cluster.
- No external cron, Celery, Airflow, or APScheduler dependency in the first
  implementation.
- No polished workbench UI for schedule editing in this phase.
- No per-user authorization model beyond the existing data-source bearer token.
- No process/service management from the IM Agent skill.
- No cancellation of an already running data job in this phase.
- No full cron expression parser in the first implementation.
- No automatic inference of trading calendars for A-share schedules.

## 4. Concepts

### 4.1 Schedule

A schedule is a persisted rule that knows when to submit a crawl job and what job
payload to submit.

```text
Schedule = trigger + repeat policy + job template + runtime state
```

### 4.2 Trigger

The trigger defines when the scheduler should fire.

First version trigger kinds:

```json
{"type": "once", "run_at": "2026-05-18T09:00:00+08:00"}
{"type": "interval", "every": 1, "unit": "hours", "start_at": "2026-05-18T09:00:00+08:00", "timezone": "Asia/Shanghai"}
{"type": "daily", "time": "08:30", "timezone": "Asia/Shanghai"}
{"type": "weekly", "days_of_week": ["mon", "wed", "fri"], "time": "08:30", "timezone": "Asia/Shanghai"}
```

`timezone` defaults to `Asia/Shanghai`. Timestamps should be ISO 8601 strings.
The backend should normalize all internal comparisons to timezone-aware
datetimes.

### 4.3 Repeat Policy

The repeat policy controls how many times a schedule is allowed to fire.

```json
{"mode": "forever"}
{"mode": "count", "count": 24}
{"mode": "until", "until": "2026-05-31T23:59:59+08:00"}
```

`once` triggers imply a maximum of one run even if `repeat.mode` is omitted.

### 4.4 Job Template

The job template describes the data job that will be submitted when the schedule
fires. It should be AI-friendly and should not require the caller to know
server-side `bars_root` or `metadata` paths.

```json
{
  "source_id": "bitget",
  "symbols": ["BTC/USDT", "ETH/USDT"],
  "frequencies": ["1d", "4h", "1h"],
  "date_range": {
    "type": "last_n_days",
    "days": 7
  },
  "page_delay_seconds": 0.35,
  "retry": {
    "max_attempts": 5,
    "request_delay_seconds": 0.5,
    "failure_cooldown_seconds": 30,
    "continue_on_error": true
  }
}
```

The backend compiles `source_id` through `DataSourceServerConfig.source()`:

- `source_id=bitget` becomes `source=ccxt`, `exchange=bitget`,
  `adjust=none`, and the configured Bitget `bars_root` and `metadata`.
- `source_id=a_share` becomes `source=akshare`, `exchange=null`,
  `adjust=qfq`, and the configured A-share `bars_root` and `metadata`.

Callers may provide explicit `source`, `exchange`, or `adjust` only when they
need to override source defaults. The backend should reject overrides that
conflict with the selected source configuration.

Supported date range modes:

```json
{"type": "fixed", "start_date": "2026-05-01", "end_date": "2026-05-18"}
{"type": "last_n_days", "days": 7, "end_offset_days": 0}
```

`last_n_days` is recommended for recurring refresh jobs because the existing
data sync service can skip already covered ranges and refill recent gaps. The
date range compiles into concrete `start_date` and `end_date` immediately before
each run is submitted.

### 4.5 Overlap Policy

The first version should support:

```json
"overlap_policy": "skip"
"overlap_policy": "allow"
```

Default: `skip`.

When `skip` is used and the previous scheduled job is still `submitted` or
`running`, the scheduler records a skipped run and computes the next fire time
without submitting a duplicate crawl job.

### 4.6 Runtime State

Schedule state is separate from job state:

- schedule `enabled`: whether the scheduler may fire it
- schedule `status`: `enabled`, `disabled`, `completed`, or `error`
- `run_count`: number of successful submissions, not number of successful data
  jobs
- `next_run_at`: next computed fire time
- `last_run_at`: most recent trigger attempt time
- `last_job_id`: most recent submitted data job id
- `last_error`: validation or submission error from the most recent trigger

Detailed crawl success/failure remains owned by `/api/data/jobs/<job_id>` and
`/api/data/tasks`.

## 5. HTTP API

All schedule endpoints use the same bearer-token authorization as the existing
data-source API.

### 5.1 Schedule Options

```text
GET /api/data/schedule-options
```

This endpoint is primarily for AI agents and thin clients. It should return
server-supported values and examples:

```json
{
  "timezone_default": "Asia/Shanghai",
  "trigger_types": ["once", "interval", "daily", "weekly"],
  "repeat_modes": ["forever", "count", "until"],
  "overlap_policies": ["skip", "allow"],
  "date_range_types": ["fixed", "last_n_days"],
  "frequencies": ["1d", "4h", "1h", "30m", "15m", "5m", "1m"],
  "sources": [
    {
      "source_id": "bitget",
      "source_label": "Bitget",
      "asset_class": "crypto",
      "default_source": "ccxt",
      "default_exchange": "bitget",
      "default_adjust": "none",
      "default_frequencies": ["1d", "4h", "1h", "30m", "15m", "5m", "1m"]
    },
    {
      "source_id": "a_share",
      "source_label": "A-share",
      "asset_class": "equity",
      "default_source": "akshare",
      "default_exchange": null,
      "default_adjust": "qfq",
      "default_frequencies": ["1d"]
    }
  ],
  "example": {
    "name": "bitget-core-hourly",
    "enabled": false,
    "trigger": {
      "type": "interval",
      "every": 1,
      "unit": "hours",
      "timezone": "Asia/Shanghai"
    },
    "repeat": {"mode": "count", "count": 24},
    "job": {
      "source_id": "bitget",
      "symbols": ["BTC/USDT"],
      "frequencies": ["1h"],
      "date_range": {"type": "last_n_days", "days": 7}
    },
    "overlap_policy": "skip"
  }
}
```

### 5.2 List Schedules

```text
GET /api/data/schedules
```

Response:

```json
{
  "schedules": [
    {
      "schedule_id": "20260518090000-bitget-core-hourly",
      "name": "bitget-core-hourly",
      "enabled": true,
      "status": "enabled",
      "run_count": 3,
      "next_run_at": "2026-05-18T12:00:00+08:00",
      "last_run_at": "2026-05-18T11:00:00+08:00",
      "last_job_id": "20260518110000-bitget-core-hourly",
      "last_error": null
    }
  ]
}
```

### 5.3 Create Schedule

```text
POST /api/data/schedules
Content-Type: application/json
```

Create requests use the full schedule payload:

```json
{
  "name": "bitget-core-hourly",
  "enabled": false,
  "trigger": {
    "type": "interval",
    "every": 1,
    "unit": "hours",
    "start_at": "2026-05-18T09:00:00+08:00",
    "timezone": "Asia/Shanghai"
  },
  "repeat": {"mode": "count", "count": 24},
  "job": {
    "source_id": "bitget",
    "symbols": ["BTC/USDT", "ETH/USDT"],
    "frequencies": ["1d", "4h", "1h"],
    "date_range": {"type": "last_n_days", "days": 7},
    "page_delay_seconds": 0.35,
    "retry": {
      "max_attempts": 5,
      "request_delay_seconds": 0.5,
      "failure_cooldown_seconds": 30,
      "continue_on_error": true
    }
  },
  "overlap_policy": "skip"
}
```

Schedules should default to `enabled=false` when the field is omitted. This
gives an IM Agent a safe creation flow: create the schedule, show the parsed
schedule to the user, then enable it after explicit confirmation.

### 5.4 Detail, Update, Delete

```text
GET    /api/data/schedules/<schedule_id>
PATCH  /api/data/schedules/<schedule_id>
DELETE /api/data/schedules/<schedule_id>
```

`PATCH` accepts partial updates. Updating `trigger`, `repeat`, or `job`
revalidates the merged schedule and recomputes `next_run_at`. Deleting a
schedule removes future triggers but does not delete already submitted data jobs
or crawl tasks.

### 5.5 Enable, Disable, Run Now

```text
POST /api/data/schedules/<schedule_id>/enable
POST /api/data/schedules/<schedule_id>/disable
POST /api/data/schedules/<schedule_id>/run-now
```

`enable` recomputes `next_run_at` from the current time. `disable` prevents
future automatic triggers. `run-now` submits one job immediately using the
schedule job template, records a schedule run, increments `run_count`, and
returns the created data job snapshot.

### 5.6 Schedule Runs

```text
GET /api/data/schedules/<schedule_id>/runs
```

Response:

```json
{
  "runs": [
    {
      "run_id": "20260518110000-bitget-core-hourly",
      "schedule_id": "20260518090000-bitget-core-hourly",
      "due_at": "2026-05-18T11:00:00+08:00",
      "triggered_at": "2026-05-18T11:00:03+08:00",
      "status": "submitted",
      "job_id": "20260518110003-bitget-core-hourly",
      "error": null
    }
  ]
}
```

Run status values:

```text
submitted
skipped
failed
```

The schedule run record only describes whether a data job was submitted. The
data job's execution status remains available from `/api/data/jobs/<job_id>`.

## 6. Python Architecture

Add a scheduler module under the existing data-source package:

```text
backtest/data_source/schedules.py
```

Responsibilities:

- pydantic models for triggers, repeat policy, job template, schedule config,
  schedule snapshots, and run snapshots
- `DataSourceScheduleStore` for SQLite persistence
- `DataSourceScheduleService` for create/list/detail/update/delete/enable/
  disable/run-now operations
- `DataSourceScheduler` for the background loop
- pure functions for computing next run times and compiling job templates into
  `DataSyncJobConfig` payloads

Modify:

```text
backtest/data_source/config.py
backtest/data_source/api.py
backtest/data_source/server.py
backtest/cli/data_source.py
backtest/data_source/__init__.py
```

### 6.1 Config

`DataSourceServerConfig` should gain:

```python
schedule_db_path: Path = Path("data/data_source_schedules.sqlite")
scheduler_poll_seconds: float = 5.0
```

The CLI should expose:

```text
--schedule-db data/data_source_schedules.sqlite
--scheduler-poll-seconds 5
--no-scheduler
```

`--no-scheduler` should disable automatic background firing while preserving
schedule CRUD endpoints. This is useful for tests, dry operations, or a standby
server.

### 6.2 Service Wiring

`backtest data-source serve` should build the service in this order:

1. Create `DataSourceServerConfig`.
2. Create `DataSourceJobRegistry`.
3. Create `DataSourceApi`.
4. Create `DataSourceScheduleStore`.
5. Create `DataSourceScheduleService` with `submit_job=api.submit_job` and
   `get_job=api.job`.
6. Attach the schedule service to `DataSourceApi`.
7. Start `DataSourceScheduler` unless `--no-scheduler` was passed.
8. Start the HTTP server.

This makes schedule execution go through the same `DataSourceApi.submit_job()`
normalization and validation path as direct `POST /api/data/jobs` requests.

### 6.3 Persistence

Use a dedicated SQLite database instead of mixing schedule state into each
source's market-data metadata database.

Tables:

```sql
CREATE TABLE IF NOT EXISTS data_schedules (
  schedule_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  config_json TEXT NOT NULL,
  enabled INTEGER NOT NULL,
  status TEXT NOT NULL,
  run_count INTEGER NOT NULL,
  next_run_at TEXT,
  last_run_at TEXT,
  last_job_id TEXT,
  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

```sql
CREATE TABLE IF NOT EXISTS data_schedule_runs (
  run_id TEXT PRIMARY KEY,
  schedule_id TEXT NOT NULL,
  due_at TEXT NOT NULL,
  triggered_at TEXT NOT NULL,
  status TEXT NOT NULL,
  job_id TEXT,
  error TEXT,
  created_at TEXT NOT NULL
);
```

The store should use short transactions around each create/update/trigger
operation. The first version does not need cross-process locking because the
current server is a single process.

### 6.4 Scheduler Loop

`DataSourceScheduler` runs in one daemon thread. Every poll:

1. Read enabled schedules where `next_run_at <= now`.
2. For each schedule, acquire the store lock.
3. If repeat policy is exhausted, mark it `completed`.
4. If `overlap_policy=skip` and `get_job(last_job_id)` shows the previous data
   job is still `submitted` or `running`, write a skipped run and compute the
   next run time.
5. Otherwise compile the job template into a concrete `POST /api/data/jobs`
   payload and call `submit_job(payload)`.
6. Record `job_id`, increment `run_count`, write run history, compute
   `next_run_at`.
7. If validation or submission fails, record a failed run, store `last_error`,
   and compute the next run time unless the repeat policy is exhausted.

The loop should catch exceptions per schedule so one bad schedule cannot kill
the scheduler thread.

### 6.5 Misfire Behavior

If the server is down when a schedule should have fired, the first version uses
`misfire_policy=skip_missed` implicitly:

- on startup, enabled schedules recompute the next future `next_run_at`
- no backlog of missed runs is submitted automatically

This avoids surprise API bursts after a restart. A later version can add
`run_once_on_startup` if needed.

## 7. IM Agent Skill Updates

Update `.codex/skills/backtest-im-agent-api`:

- `SKILL.md`: include schedule management in the trigger description and allowed
  API surface.
- `references/data-source-http-api.md`: document schedule endpoints and payloads.
- `references/dialogue-flows.md`: add schedule creation, update, enable,
  disable, run-now, and read flows.

IM Agent behavior:

- For read-only schedule questions, use the narrowest schedule endpoint.
- Before creating or modifying a schedule, call `GET /api/data/schedule-options`
  when source defaults or supported fields are unknown.
- Show a concise final schedule summary before any write call.
- Require explicit confirmation before `POST`, `PATCH`, `DELETE`, `enable`,
  `disable`, or `run-now`.
- Never print bearer tokens.
- Never operate server processes or deployment files from the IM boundary.

## 8. Error Handling

- Unknown schedule id: 404 JSON error.
- Invalid JSON body: 400 JSON error.
- Invalid trigger, repeat, job template, source id, symbol, frequency, or date
  range: 400 JSON error.
- Scheduler thread errors: record `last_error` and a failed schedule run.
- Direct HTTP request failures should not expose stack traces.
- Background job failure after submission remains visible through the existing
  job status endpoint.

## 9. Testing

Add tests before implementation:

- schedule model validation for trigger, repeat, date range, source id, and
  overlap policy
- next-run computation for once, interval, daily, weekly, count, until, and
  exhausted schedules
- job template compilation into a valid existing data job payload
- SQLite store create/list/get/update/delete and run history persistence
- API facade schedule CRUD, enable, disable, and run-now
- HTTP routes for schedule options and schedule management
- scheduler loop submitting due schedules through an injected fake submitter
- overlap skip behavior when the last job is still running
- CLI wiring for `--schedule-db`, `--scheduler-poll-seconds`, and
  `--no-scheduler`
- skill documentation references for schedule endpoints

The tests should not call real exchanges or sleep for real intervals. Use an
injectable `now()` and a single-iteration scheduler tick method for deterministic
tests.

## 10. Acceptance Criteria

- A data-source server can be started with schedule persistence enabled:

```bash
uv run backtest data-source serve \
  --host 127.0.0.1 \
  --port 8768 \
  --schedule-db data/data_source_schedules.sqlite
```

- `GET /api/data/schedule-options` returns source defaults and schedule examples.
- `POST /api/data/schedules` creates a disabled schedule by default.
- `POST /api/data/schedules/<schedule_id>/enable` enables it and computes
  `next_run_at`.
- The scheduler automatically submits jobs through the existing job path when a
  schedule is due.
- `POST /api/data/schedules/<schedule_id>/run-now` immediately submits one job
  and returns a normal data job snapshot.
- `PATCH /api/data/schedules/<schedule_id>` can update trigger time, repeat
  policy, symbols, frequencies, date range, retry policy, and enabled state.
- `GET /api/data/schedules/<schedule_id>/runs` shows submitted, skipped, or
  failed trigger attempts.
- Existing `/api/data/jobs` and `/api/data/tasks` behavior remains unchanged.
- `backtest-im-agent-api` documents how an IM Agent should safely manage
  schedules over HTTP.

## 11. Future Work

- Workbench schedule management UI.
- Additional repeat forms such as monthly schedules.
- Optional cron-expression support if a real need appears.
- Cancellation or pause/resume for already running data jobs.
- Better data-window strategies such as "from last successful catalog coverage".
- Schedule-level rate limits and per-source concurrency caps.
- Audit logs with requester identity if multi-user access is added.
