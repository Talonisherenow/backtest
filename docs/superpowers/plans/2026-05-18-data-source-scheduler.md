# Data Source Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an HTTP-managed scheduler to the data-source backend so agents can create, enable, disable, update, and manually run recurring data crawl job submissions.

**Architecture:** Add a focused `backtest.data_source.schedules` module for schedule models, SQLite persistence, trigger calculation, job-template compilation, and a background scheduler loop. Wire it into the existing `DataSourceApi.submit_job()` path so scheduled runs submit the same validated data job payloads as `POST /api/data/jobs`. Extend the stdlib HTTP adapter, CLI, tests, and IM Agent skill docs around that service.

**Tech Stack:** Python 3.11, stdlib `zoneinfo`, stdlib `sqlite3`, stdlib `threading`, pydantic v2, Typer, pytest, existing `ThreadingHTTPServer`.

---

## File Structure

- Create `backtest/data_source/schedules.py`: schedule models, trigger helpers, SQLite store, service facade, and scheduler loop.
- Modify `backtest/data_source/config.py`: add schedule DB and scheduler polling configuration.
- Modify `backtest/data_source/api.py`: add schedule service delegation methods.
- Modify `backtest/data_source/server.py`: add schedule HTTP routes and `PATCH` support.
- Modify `backtest/data_source/__init__.py`: export scheduler public classes used by tests and CLI.
- Modify `backtest/cli/data_source.py`: add CLI options and scheduler startup wiring.
- Modify `tests/data_source/test_schedules.py`: cover models, time calculation, job payload compilation, store, service, and scheduler tick behavior.
- Modify `tests/data_source/test_api.py`: cover API facade schedule methods.
- Modify `tests/data_source/test_server.py`: cover HTTP schedule routes.
- Modify `tests/test_cli_commands.py`: cover scheduler CLI options and service wiring.
- Modify `.codex/skills/backtest-im-agent-api/SKILL.md`: add schedule endpoint authority rules.
- Modify `.codex/skills/backtest-im-agent-api/references/data-source-http-api.md`: document schedule HTTP API.
- Modify `.codex/skills/backtest-im-agent-api/references/dialogue-flows.md`: add schedule management conversation flow.
- Modify `.codex/skills/backtest-data-source-ops/SKILL.md`: mention schedule management for operators.
- Modify `.codex/skills/backtest-data-source-ops/references/data-job-fields.md`: mention schedule job template fields.
- Modify `docs/market-data-operations.md`: add operator examples for schedules.
- Modify `docs/remote-workbench-deployment.md`: add remote schedule API examples and security note.

## Task 1: Schedule Models And Time Helpers

**Files:**
- Create: `backtest/data_source/schedules.py`
- Test: `tests/data_source/test_schedules.py`

- [ ] **Step 1: Write failing model and time-helper tests**

Add `tests/data_source/test_schedules.py` with these tests:

```python
from datetime import date, datetime
from pathlib import Path

import pytest

from backtest.data_source.config import DataSourceServerConfig, DataSourceSpec
from backtest.data_source.schedules import (
    DataScheduleConfig,
    build_job_payload,
    compute_next_run_at,
)


def _server_config(tmp_path: Path) -> DataSourceServerConfig:
    bars_root = tmp_path / "bars"
    bars_root.mkdir()
    return DataSourceServerConfig(
        sources=[
            DataSourceSpec(
                source_id="bitget",
                source_label="Bitget",
                asset_class="crypto",
                bars_root=bars_root,
                metadata_path=tmp_path / "metadata.sqlite",
                adjust="none",
                catalog_source="ccxt:bitget",
            )
        ]
    )


def test_interval_schedule_defaults_to_disabled_and_computes_next_run():
    schedule = DataScheduleConfig.model_validate(
        {
            "name": "bitget-hourly",
            "trigger": {
                "type": "interval",
                "every": 1,
                "unit": "hours",
                "start_at": "2026-05-18T09:00:00+08:00",
                "timezone": "Asia/Shanghai",
            },
            "repeat": {"mode": "count", "count": 3},
            "job": {
                "source_id": "bitget",
                "symbols": ["BTC/USDT"],
                "frequencies": ["1h"],
                "date_range": {"type": "last_n_days", "days": 7},
            },
        }
    )

    assert schedule.enabled is False
    assert schedule.overlap_policy == "skip"
    next_run = compute_next_run_at(
        schedule,
        now=datetime.fromisoformat("2026-05-18T08:00:00+08:00"),
        run_count=0,
    )
    assert next_run.isoformat() == "2026-05-18T09:00:00+08:00"


def test_repeat_count_exhaustion_has_no_next_run():
    schedule = DataScheduleConfig.model_validate(
        {
            "name": "limited",
            "trigger": {"type": "interval", "every": 1, "unit": "hours"},
            "repeat": {"mode": "count", "count": 2},
            "job": {
                "source_id": "bitget",
                "symbols": ["BTC/USDT"],
                "frequencies": ["1h"],
                "date_range": {"type": "last_n_days", "days": 3},
            },
        }
    )

    assert compute_next_run_at(
        schedule,
        now=datetime.fromisoformat("2026-05-18T10:00:00+08:00"),
        run_count=2,
    ) is None


def test_daily_and_weekly_triggers_use_local_wall_clock_time():
    daily = DataScheduleConfig.model_validate(
        {
            "name": "daily",
            "trigger": {"type": "daily", "time": "08:30", "timezone": "Asia/Shanghai"},
            "job": {
                "source_id": "bitget",
                "symbols": ["BTC/USDT"],
                "frequencies": ["1d"],
                "date_range": {"type": "last_n_days", "days": 7},
            },
        }
    )
    weekly = DataScheduleConfig.model_validate(
        {
            "name": "weekly",
            "trigger": {
                "type": "weekly",
                "days_of_week": ["mon", "wed"],
                "time": "08:30",
                "timezone": "Asia/Shanghai",
            },
            "job": {
                "source_id": "bitget",
                "symbols": ["BTC/USDT"],
                "frequencies": ["1d"],
                "date_range": {"type": "last_n_days", "days": 7},
            },
        }
    )

    assert compute_next_run_at(
        daily,
        now=datetime.fromisoformat("2026-05-18T09:00:00+08:00"),
        run_count=0,
    ).isoformat() == "2026-05-19T08:30:00+08:00"
    assert compute_next_run_at(
        weekly,
        now=datetime.fromisoformat("2026-05-18T09:00:00+08:00"),
        run_count=0,
    ).isoformat() == "2026-05-20T08:30:00+08:00"


def test_job_template_compiles_to_existing_data_job_payload(tmp_path: Path):
    schedule = DataScheduleConfig.model_validate(
        {
            "name": "bitget-refresh",
            "trigger": {"type": "once", "run_at": "2026-05-18T09:00:00+08:00"},
            "job": {
                "source_id": "bitget",
                "symbols": ["BTC/USDT"],
                "frequencies": ["1d", "1h"],
                "date_range": {"type": "last_n_days", "days": 7, "end_offset_days": 1},
                "page_delay_seconds": 0.35,
                "retry": {"max_attempts": 5},
            },
        }
    )

    payload = build_job_payload(
        schedule,
        _server_config(tmp_path),
        now=datetime.fromisoformat("2026-05-18T12:00:00+08:00"),
    )

    assert payload["name"] == "scheduled-bitget-refresh"
    assert payload["source"] == "ccxt"
    assert payload["exchange"] == "bitget"
    assert payload["symbols"] == ["BTC/USDT"]
    assert payload["frequencies"] == ["1d", "1h"]
    assert payload["adjust"] == "none"
    assert payload["start_date"] == "2026-05-10"
    assert payload["end_date"] == "2026-05-17"
    assert payload["bars_root"] == str(tmp_path / "bars")
    assert payload["metadata"] == str(tmp_path / "metadata.sqlite")
    assert payload["page_delay_seconds"] == 0.35
    assert payload["retry"]["max_attempts"] == 5


def test_invalid_schedule_fields_raise_validation_errors():
    with pytest.raises(ValueError, match="symbols"):
        DataScheduleConfig.model_validate(
            {
                "name": "bad",
                "trigger": {"type": "interval", "every": 1, "unit": "hours"},
                "job": {
                    "source_id": "bitget",
                    "symbols": [],
                    "frequencies": ["1h"],
                    "date_range": {"type": "last_n_days", "days": 7},
                },
            }
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source/test_schedules.py -q
```

Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `backtest.data_source.schedules`.

- [ ] **Step 3: Implement models and helper functions**

Create `backtest/data_source/schedules.py` with the first implementation:

```python
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

from backtest.core.enums import AdjustMode, Frequency
from backtest.core.symbols import normalize_symbol
from backtest.data.jobs import RetryConfig
from backtest.data_source.config import DataSourceServerConfig


WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


class TriggerConfig(BaseModel):
    type: Literal["once", "interval", "daily", "weekly"]
    timezone: str = "Asia/Shanghai"
    run_at: datetime | None = None
    start_at: datetime | None = None
    every: int | None = Field(default=None, ge=1)
    unit: Literal["minutes", "hours", "days"] | None = None
    time: str | None = None
    days_of_week: list[str] = Field(default_factory=list)

    @field_validator("days_of_week")
    @classmethod
    def normalize_days(cls, value: list[str]) -> list[str]:
        days = [item.strip().lower() for item in value]
        invalid = [item for item in days if item not in WEEKDAYS]
        if invalid:
            raise ValueError(f"Unsupported days_of_week: {invalid}")
        return days

    @model_validator(mode="after")
    def validate_trigger(self) -> "TriggerConfig":
        ZoneInfo(self.timezone)
        if self.type == "once" and self.run_at is None:
            raise ValueError("run_at is required for once trigger")
        if self.type == "interval" and (self.every is None or self.unit is None):
            raise ValueError("every and unit are required for interval trigger")
        if self.type in {"daily", "weekly"} and self.time is None:
            raise ValueError("time is required for daily and weekly triggers")
        if self.type == "weekly" and not self.days_of_week:
            raise ValueError("days_of_week is required for weekly trigger")
        if self.time is not None:
            time.fromisoformat(self.time)
        return self


class RepeatConfig(BaseModel):
    mode: Literal["forever", "count", "until"] = "forever"
    count: int | None = Field(default=None, ge=1)
    until: datetime | None = None

    @model_validator(mode="after")
    def validate_repeat(self) -> "RepeatConfig":
        if self.mode == "count" and self.count is None:
            raise ValueError("count is required when repeat.mode=count")
        if self.mode == "until" and self.until is None:
            raise ValueError("until is required when repeat.mode=until")
        return self


class DateRangeConfig(BaseModel):
    type: Literal["fixed", "last_n_days"]
    start_date: date | None = None
    end_date: date | None = None
    days: int | None = Field(default=None, ge=1)
    end_offset_days: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> "DateRangeConfig":
        if self.type == "fixed":
            if self.start_date is None or self.end_date is None:
                raise ValueError("start_date and end_date are required for fixed date_range")
            if self.end_date < self.start_date:
                raise ValueError("end_date must be on or after start_date")
        if self.type == "last_n_days" and self.days is None:
            raise ValueError("days is required for last_n_days date_range")
        return self


class ScheduleJobTemplate(BaseModel):
    source_id: str
    symbols: list[str]
    frequencies: list[Frequency]
    date_range: DateRangeConfig
    source: str | None = None
    exchange: str | None = None
    adjust: AdjustMode | None = None
    page_delay_seconds: float = Field(default=0.0, ge=0)
    retry: RetryConfig = Field(default_factory=RetryConfig)

    @field_validator("source_id")
    @classmethod
    def normalize_source_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("source_id must not be empty")
        return normalized

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("symbols must not be empty")
        return [normalize_symbol(symbol) for symbol in value]

    @field_validator("frequencies")
    @classmethod
    def validate_frequencies(cls, value: list[Frequency]) -> list[Frequency]:
        if not value:
            raise ValueError("frequencies must not be empty")
        return value


class DataScheduleConfig(BaseModel):
    name: str
    enabled: bool = False
    trigger: TriggerConfig
    repeat: RepeatConfig = Field(default_factory=RepeatConfig)
    job: ScheduleJobTemplate
    overlap_policy: Literal["skip", "allow"] = "skip"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be empty")
        return normalized


def compute_next_run_at(
    schedule: DataScheduleConfig,
    *,
    now: datetime,
    run_count: int,
) -> datetime | None:
    if _is_exhausted(schedule, now=now, run_count=run_count):
        return None
    trigger = schedule.trigger
    zone = ZoneInfo(trigger.timezone)
    local_now = _aware(now, zone)
    if trigger.type == "once":
        candidate = _aware(trigger.run_at, zone)
        return candidate if run_count == 0 and candidate >= local_now else None
    if trigger.type == "interval":
        return _next_interval(trigger, local_now)
    if trigger.type == "daily":
        return _next_daily(trigger, local_now)
    return _next_weekly(trigger, local_now)


def build_job_payload(
    schedule: DataScheduleConfig,
    server_config: DataSourceServerConfig,
    *,
    now: datetime,
) -> dict[str, Any]:
    spec = server_config.source(schedule.job.source_id)
    source, exchange = _source_and_exchange(spec.catalog_source)
    adjust = schedule.job.adjust.value if schedule.job.adjust else spec.adjust
    if schedule.job.source is not None and schedule.job.source != source:
        raise ValueError(f"source override conflicts with source_id={spec.source_id}")
    if schedule.job.exchange is not None and schedule.job.exchange != exchange:
        raise ValueError(f"exchange override conflicts with source_id={spec.source_id}")
    start_date, end_date = _date_range(schedule.job.date_range, now=now)
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", schedule.name).strip("-") or "schedule"
    return {
        "name": f"scheduled-{safe_name}",
        "source": source,
        "exchange": exchange,
        "symbols": schedule.job.symbols,
        "frequencies": [frequency.value for frequency in schedule.job.frequencies],
        "adjust": adjust,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "bars_root": str(spec.bars_root),
        "metadata": str(spec.metadata_path),
        "output_dir": str(Path("runs/data_jobs") / safe_name),
        "page_delay_seconds": schedule.job.page_delay_seconds,
        "retry": schedule.job.retry.model_dump(mode="json"),
    }


def _is_exhausted(schedule: DataScheduleConfig, *, now: datetime, run_count: int) -> bool:
    if schedule.trigger.type == "once" and run_count >= 1:
        return True
    if schedule.repeat.mode == "count" and schedule.repeat.count is not None:
        return run_count >= schedule.repeat.count
    if schedule.repeat.mode == "until" and schedule.repeat.until is not None:
        return now > schedule.repeat.until
    return False


def _aware(value: datetime | None, zone: ZoneInfo) -> datetime:
    if value is None:
        raise ValueError("datetime value is required")
    if value.tzinfo is None:
        return value.replace(tzinfo=zone)
    return value.astimezone(zone)


def _next_interval(trigger: TriggerConfig, now: datetime) -> datetime:
    start = _aware(trigger.start_at, now.tzinfo) if trigger.start_at else now
    delta = {
        "minutes": timedelta(minutes=trigger.every or 1),
        "hours": timedelta(hours=trigger.every or 1),
        "days": timedelta(days=trigger.every or 1),
    }[trigger.unit or "hours"]
    if start >= now:
        return start
    elapsed = now - start
    steps = int(elapsed.total_seconds() // delta.total_seconds()) + 1
    return start + delta * steps


def _next_daily(trigger: TriggerConfig, now: datetime) -> datetime:
    local_time = time.fromisoformat(trigger.time or "00:00")
    candidate = now.replace(
        hour=local_time.hour,
        minute=local_time.minute,
        second=local_time.second,
        microsecond=0,
    )
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    return candidate


def _next_weekly(trigger: TriggerConfig, now: datetime) -> datetime:
    local_time = time.fromisoformat(trigger.time or "00:00")
    allowed = {WEEKDAYS[item] for item in trigger.days_of_week}
    for offset in range(0, 8):
        candidate_date = now.date() + timedelta(days=offset)
        if candidate_date.weekday() not in allowed:
            continue
        candidate = datetime.combine(candidate_date, local_time, tzinfo=now.tzinfo)
        if candidate > now:
            return candidate
    raise ValueError("Unable to compute weekly next run")


def _date_range(config: DateRangeConfig, *, now: datetime) -> tuple[date, date]:
    if config.type == "fixed":
        return config.start_date, config.end_date
    end_date = now.date() - timedelta(days=config.end_offset_days)
    start_date = end_date - timedelta(days=(config.days or 1) - 1)
    return start_date, end_date


def _source_and_exchange(catalog_source: str) -> tuple[str, str | None]:
    if catalog_source.startswith("ccxt:"):
        return "ccxt", catalog_source.split(":", 1)[1]
    return catalog_source, None
```

- [ ] **Step 4: Run tests to verify Task 1 passes**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source/test_schedules.py -q
```

Expected: PASS for the Task 1 tests.

- [ ] **Step 5: Commit Task 1**

```bash
git add backtest/data_source/schedules.py tests/data_source/test_schedules.py
git commit -m "feat: add data source schedule models"
```

## Task 2: SQLite Schedule Store

**Files:**
- Modify: `backtest/data_source/schedules.py`
- Test: `tests/data_source/test_schedules.py`

- [ ] **Step 1: Add failing store persistence tests**

Append these tests to `tests/data_source/test_schedules.py`:

```python
from backtest.data_source.schedules import DataSourceScheduleStore


def _schedule_config() -> DataScheduleConfig:
    return DataScheduleConfig.model_validate(
        {
            "name": "bitget-hourly",
            "enabled": True,
            "trigger": {"type": "interval", "every": 1, "unit": "hours"},
            "repeat": {"mode": "count", "count": 2},
            "job": {
                "source_id": "bitget",
                "symbols": ["BTC/USDT"],
                "frequencies": ["1h"],
                "date_range": {"type": "last_n_days", "days": 7},
            },
        }
    )


def test_schedule_store_persists_schedule_snapshots(tmp_path: Path):
    store = DataSourceScheduleStore(
        tmp_path / "schedules.sqlite",
        now=lambda: datetime.fromisoformat("2026-05-18T09:00:00+08:00"),
    )

    snapshot = store.create(_schedule_config(), next_run_at=datetime.fromisoformat("2026-05-18T10:00:00+08:00"))
    loaded = store.get(snapshot.schedule_id)

    assert loaded.schedule_id == snapshot.schedule_id
    assert loaded.name == "bitget-hourly"
    assert loaded.enabled is True
    assert loaded.status == "enabled"
    assert loaded.run_count == 0
    assert loaded.next_run_at.isoformat() == "2026-05-18T10:00:00+08:00"
    assert loaded.config.job.symbols == ["BTC/USDT"]
    assert [item.schedule_id for item in store.list()] == [snapshot.schedule_id]


def test_schedule_store_updates_deletes_and_records_runs(tmp_path: Path):
    store = DataSourceScheduleStore(
        tmp_path / "schedules.sqlite",
        now=lambda: datetime.fromisoformat("2026-05-18T09:00:00+08:00"),
    )
    snapshot = store.create(_schedule_config(), next_run_at=datetime.fromisoformat("2026-05-18T10:00:00+08:00"))

    updated = store.update_state(
        snapshot.schedule_id,
        enabled=False,
        status="disabled",
        run_count=1,
        next_run_at=None,
        last_run_at=datetime.fromisoformat("2026-05-18T10:00:02+08:00"),
        last_job_id="job-1",
        last_error=None,
    )
    run = store.record_run(
        schedule_id=snapshot.schedule_id,
        due_at=datetime.fromisoformat("2026-05-18T10:00:00+08:00"),
        triggered_at=datetime.fromisoformat("2026-05-18T10:00:02+08:00"),
        status="submitted",
        job_id="job-1",
        error=None,
    )

    assert updated.enabled is False
    assert updated.status == "disabled"
    assert updated.run_count == 1
    assert run.status == "submitted"
    assert store.runs(snapshot.schedule_id)[0].job_id == "job-1"

    store.delete(snapshot.schedule_id)
    with pytest.raises(ValueError, match="Unknown schedule"):
        store.get(snapshot.schedule_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source/test_schedules.py -q
```

Expected: FAIL with `ImportError` for `DataSourceScheduleStore`.

- [ ] **Step 3: Implement snapshots and store**

Extend `backtest/data_source/schedules.py` with:

```python
import json
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class DataScheduleSnapshot:
    schedule_id: str
    name: str
    config: DataScheduleConfig
    enabled: bool
    status: str
    run_count: int
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_job_id: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "name": self.name,
            "config": self.config.model_dump(mode="json"),
            "enabled": self.enabled,
            "status": self.status,
            "run_count": self.run_count,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_job_id": self.last_job_id,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class DataScheduleRunSnapshot:
    run_id: str
    schedule_id: str
    due_at: datetime
    triggered_at: datetime
    status: str
    job_id: str | None
    error: str | None
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "schedule_id": self.schedule_id,
            "due_at": self.due_at.isoformat(),
            "triggered_at": self.triggered_at.isoformat(),
            "status": self.status,
            "job_id": self.job_id,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
        }


class DataSourceScheduleStore:
    def __init__(self, path: str | Path, *, now: Callable[[], datetime] = datetime.now) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.now = now
        self._lock = threading.Lock()
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def create(
        self,
        config: DataScheduleConfig,
        *,
        next_run_at: datetime | None,
    ) -> DataScheduleSnapshot:
        now = self.now()
        schedule_id = self._unique_id("data_schedules", "schedule_id", now, config.name)
        status = "enabled" if config.enabled else "disabled"
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO data_schedules
                (schedule_id, name, config_json, enabled, status, run_count, next_run_at,
                 last_run_at, last_job_id, last_error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    schedule_id,
                    config.name,
                    json.dumps(config.model_dump(mode="json"), ensure_ascii=False),
                    int(config.enabled),
                    status,
                    0,
                    next_run_at.isoformat() if next_run_at else None,
                    None,
                    None,
                    None,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return self.get(schedule_id)

    def list(self) -> list[DataScheduleSnapshot]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM data_schedules ORDER BY created_at, schedule_id"
            ).fetchall()
        return [self._snapshot(row) for row in rows]

    def due(self, now: datetime) -> list[DataScheduleSnapshot]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM data_schedules
                WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?
                ORDER BY next_run_at, schedule_id
                """,
                (now.isoformat(),),
            ).fetchall()
        return [self._snapshot(row) for row in rows]

    def get(self, schedule_id: str) -> DataScheduleSnapshot:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM data_schedules WHERE schedule_id = ?",
                (schedule_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown schedule: {schedule_id}")
        return self._snapshot(row)

    def update_config(
        self,
        schedule_id: str,
        config: DataScheduleConfig,
        *,
        next_run_at: datetime | None,
    ) -> DataScheduleSnapshot:
        now = self.now()
        status = "enabled" if config.enabled else "disabled"
        with self._lock, self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE data_schedules
                SET name = ?, config_json = ?, enabled = ?, status = ?,
                    next_run_at = ?, last_error = NULL, updated_at = ?
                WHERE schedule_id = ?
                """,
                (
                    config.name,
                    json.dumps(config.model_dump(mode="json"), ensure_ascii=False),
                    int(config.enabled),
                    status,
                    next_run_at.isoformat() if next_run_at else None,
                    now.isoformat(),
                    schedule_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Unknown schedule: {schedule_id}")
        return self.get(schedule_id)

    def update_state(
        self,
        schedule_id: str,
        *,
        enabled: bool,
        status: str,
        run_count: int,
        next_run_at: datetime | None,
        last_run_at: datetime | None,
        last_job_id: str | None,
        last_error: str | None,
    ) -> DataScheduleSnapshot:
        now = self.now()
        with self._lock, self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE data_schedules
                SET enabled = ?, status = ?, run_count = ?, next_run_at = ?,
                    last_run_at = ?, last_job_id = ?, last_error = ?, updated_at = ?
                WHERE schedule_id = ?
                """,
                (
                    int(enabled),
                    status,
                    run_count,
                    next_run_at.isoformat() if next_run_at else None,
                    last_run_at.isoformat() if last_run_at else None,
                    last_job_id,
                    last_error,
                    now.isoformat(),
                    schedule_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Unknown schedule: {schedule_id}")
        return self.get(schedule_id)

    def delete(self, schedule_id: str) -> None:
        with self._lock, self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM data_schedules WHERE schedule_id = ?",
                (schedule_id,),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Unknown schedule: {schedule_id}")

    def record_run(
        self,
        *,
        schedule_id: str,
        due_at: datetime,
        triggered_at: datetime,
        status: str,
        job_id: str | None,
        error: str | None,
    ) -> DataScheduleRunSnapshot:
        created_at = self.now()
        run_id = self._unique_id("data_schedule_runs", "run_id", triggered_at, schedule_id)
        with self._lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO data_schedule_runs
                (run_id, schedule_id, due_at, triggered_at, status, job_id, error, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    schedule_id,
                    due_at.isoformat(),
                    triggered_at.isoformat(),
                    status,
                    job_id,
                    error,
                    created_at.isoformat(),
                ),
            )
        return self.runs(schedule_id)[-1]

    def runs(self, schedule_id: str) -> list[DataScheduleRunSnapshot]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM data_schedule_runs
                WHERE schedule_id = ?
                ORDER BY triggered_at, run_id
                """,
                (schedule_id,),
            ).fetchall()
        return [self._run_snapshot(row) for row in rows]

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
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
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS data_schedule_runs (
                    run_id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    triggered_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    job_id TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

    def _snapshot(self, row: sqlite3.Row) -> DataScheduleSnapshot:
        return DataScheduleSnapshot(
            schedule_id=row["schedule_id"],
            name=row["name"],
            config=DataScheduleConfig.model_validate(json.loads(row["config_json"])),
            enabled=bool(row["enabled"]),
            status=row["status"],
            run_count=int(row["run_count"]),
            next_run_at=_parse_dt(row["next_run_at"]),
            last_run_at=_parse_dt(row["last_run_at"]),
            last_job_id=row["last_job_id"],
            last_error=row["last_error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _run_snapshot(self, row: sqlite3.Row) -> DataScheduleRunSnapshot:
        return DataScheduleRunSnapshot(
            run_id=row["run_id"],
            schedule_id=row["schedule_id"],
            due_at=datetime.fromisoformat(row["due_at"]),
            triggered_at=datetime.fromisoformat(row["triggered_at"]),
            status=row["status"],
            job_id=row["job_id"],
            error=row["error"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _unique_id(self, table: str, column: str, when: datetime, name: str) -> str:
        base = f"{when:%Y%m%d%H%M%S}-{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'schedule'}"
        with self.connect() as conn:
            rows = conn.execute(f"SELECT {column} AS value FROM {table}").fetchall()
        existing = {row["value"] for row in rows}
        candidate = base
        index = 2
        while candidate in existing:
            candidate = f"{base}-{index}"
            index += 1
        return candidate


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
```

- [ ] **Step 4: Run tests to verify Task 2 passes**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source/test_schedules.py -q
```

Expected: PASS for model and store tests.

- [ ] **Step 5: Commit Task 2**

```bash
git add backtest/data_source/schedules.py tests/data_source/test_schedules.py
git commit -m "feat: persist data source schedules"
```

## Task 3: Schedule Service And Scheduler Tick

**Files:**
- Modify: `backtest/data_source/schedules.py`
- Test: `tests/data_source/test_schedules.py`

- [ ] **Step 1: Add failing service and scheduler tests**

Append these tests to `tests/data_source/test_schedules.py`:

```python
from backtest.data_source.schedules import DataSourceScheduleService, DataSourceScheduler


def test_schedule_service_create_update_enable_disable_and_run_now(tmp_path: Path):
    submitted = []

    def submit_job(payload):
        submitted.append(payload)
        return type(
            "Snapshot",
            (),
            {
                "job_id": f"job-{len(submitted)}",
                "status": "submitted",
                "to_dict": lambda self: {"job_id": self.job_id, "status": self.status},
            },
        )()

    service = DataSourceScheduleService(
        store=DataSourceScheduleStore(
            tmp_path / "schedules.sqlite",
            now=lambda: datetime.fromisoformat("2026-05-18T09:00:00+08:00"),
        ),
        server_config=_server_config(tmp_path),
        submit_job=submit_job,
        now=lambda: datetime.fromisoformat("2026-05-18T09:00:00+08:00"),
    )

    created = service.create(
        {
            "name": "bitget-hourly",
            "trigger": {"type": "interval", "every": 1, "unit": "hours"},
            "job": {
                "source_id": "bitget",
                "symbols": ["BTC/USDT"],
                "frequencies": ["1h"],
                "date_range": {"type": "last_n_days", "days": 7},
            },
        }
    )
    enabled = service.enable(created.schedule_id)
    job = service.run_now(created.schedule_id)
    disabled = service.disable(created.schedule_id)

    assert created.enabled is False
    assert enabled.enabled is True
    assert enabled.next_run_at is not None
    assert job["job_id"] == "job-1"
    assert submitted[0]["source"] == "ccxt"
    assert disabled.enabled is False
    assert service.runs(created.schedule_id)["runs"][0]["status"] == "submitted"


def test_scheduler_tick_submits_due_schedule_once(tmp_path: Path):
    submitted = []
    now_values = iter(
        [
            datetime.fromisoformat("2026-05-18T09:00:00+08:00"),
            datetime.fromisoformat("2026-05-18T09:00:00+08:00"),
            datetime.fromisoformat("2026-05-18T09:00:00+08:00"),
        ]
    )

    def now():
        return next(now_values, datetime.fromisoformat("2026-05-18T10:00:00+08:00"))

    def submit_job(payload):
        submitted.append(payload)
        return type("Snapshot", (), {"job_id": "job-1", "status": "submitted"})()

    service = DataSourceScheduleService(
        store=DataSourceScheduleStore(tmp_path / "schedules.sqlite", now=now),
        server_config=_server_config(tmp_path),
        submit_job=submit_job,
        now=now,
    )
    snapshot = service.create(
        {
            "name": "bitget-once",
            "enabled": True,
            "trigger": {"type": "once", "run_at": "2026-05-18T09:00:00+08:00"},
            "job": {
                "source_id": "bitget",
                "symbols": ["BTC/USDT"],
                "frequencies": ["1h"],
                "date_range": {"type": "last_n_days", "days": 7},
            },
        }
    )
    scheduler = DataSourceScheduler(service=service, poll_seconds=0.01)

    scheduler.tick()

    assert len(submitted) == 1
    updated = service.get(snapshot.schedule_id)
    assert updated.run_count == 1
    assert updated.status == "completed"
    assert updated.next_run_at is None


def test_scheduler_tick_skips_when_previous_job_is_still_running(tmp_path: Path):
    submitted = []
    current_now = datetime.fromisoformat("2026-05-18T09:00:00+08:00")

    def submit_job(payload):
        submitted.append(payload)
        return type("Snapshot", (), {"job_id": "job-new", "status": "submitted"})()

    def get_job(job_id):
        return type("Snapshot", (), {"job_id": job_id, "status": "running"})()

    store = DataSourceScheduleStore(tmp_path / "schedules.sqlite", now=lambda: current_now)
    service = DataSourceScheduleService(
        store=store,
        server_config=_server_config(tmp_path),
        submit_job=submit_job,
        get_job=get_job,
        now=lambda: current_now,
    )
    snapshot = service.create(
        {
            "name": "bitget-overlap",
            "enabled": True,
            "trigger": {"type": "interval", "every": 1, "unit": "hours", "start_at": "2026-05-18T09:00:00+08:00"},
            "job": {
                "source_id": "bitget",
                "symbols": ["BTC/USDT"],
                "frequencies": ["1h"],
                "date_range": {"type": "last_n_days", "days": 7},
            },
            "overlap_policy": "skip",
        }
    )
    store.update_state(
        snapshot.schedule_id,
        enabled=True,
        status="enabled",
        run_count=0,
        next_run_at=current_now,
        last_run_at=None,
        last_job_id="job-running",
        last_error=None,
    )
    scheduler = DataSourceScheduler(service=service, poll_seconds=0.01)

    scheduler.tick()

    assert submitted == []
    updated = service.get(snapshot.schedule_id)
    assert updated.run_count == 0
    assert updated.next_run_at.isoformat() == "2026-05-18T10:00:00+08:00"
    assert service.runs(snapshot.schedule_id)["runs"][0]["status"] == "skipped"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source/test_schedules.py -q
```

Expected: FAIL with `ImportError` for `DataSourceScheduleService`.

- [ ] **Step 3: Implement service and scheduler tick**

Extend `backtest/data_source/schedules.py` with:

```python
from collections.abc import Callable
from threading import Event, Thread


class DataSourceScheduleService:
    def __init__(
        self,
        *,
        store: DataSourceScheduleStore,
        server_config: DataSourceServerConfig,
        submit_job: Callable[[dict[str, Any]], Any],
        get_job: Callable[[str], Any] | None = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.store = store
        self.server_config = server_config
        self.submit_job = submit_job
        self.get_job = get_job
        self.now = now

    def options(self) -> dict[str, Any]:
        return {
            "timezone_default": "Asia/Shanghai",
            "trigger_types": ["once", "interval", "daily", "weekly"],
            "repeat_modes": ["forever", "count", "until"],
            "overlap_policies": ["skip", "allow"],
            "date_range_types": ["fixed", "last_n_days"],
            "frequencies": [frequency.value for frequency in Frequency],
            "sources": [self._source_options(source) for source in self.server_config.sources],
        }

    def list(self) -> dict[str, list[dict[str, Any]]]:
        return {"schedules": [snapshot.to_dict() for snapshot in self.store.list()]}

    def get(self, schedule_id: str) -> DataScheduleSnapshot:
        return self.store.get(schedule_id)

    def create(self, payload: dict[str, Any]) -> DataScheduleSnapshot:
        config = DataScheduleConfig.model_validate(payload)
        next_run_at = compute_next_run_at(config, now=self.now(), run_count=0) if config.enabled else None
        return self.store.create(config, next_run_at=next_run_at)

    def update(self, schedule_id: str, payload: dict[str, Any]) -> DataScheduleSnapshot:
        current = self.store.get(schedule_id)
        merged = current.config.model_dump(mode="json")
        _deep_update(merged, payload)
        config = DataScheduleConfig.model_validate(merged)
        next_run_at = compute_next_run_at(config, now=self.now(), run_count=current.run_count) if config.enabled else None
        return self.store.update_config(schedule_id, config, next_run_at=next_run_at)

    def delete(self, schedule_id: str) -> dict[str, str]:
        self.store.delete(schedule_id)
        return {"deleted": schedule_id}

    def enable(self, schedule_id: str) -> DataScheduleSnapshot:
        current = self.store.get(schedule_id)
        config = current.config.model_copy(update={"enabled": True})
        next_run_at = compute_next_run_at(config, now=self.now(), run_count=current.run_count)
        return self.store.update_config(schedule_id, config, next_run_at=next_run_at)

    def disable(self, schedule_id: str) -> DataScheduleSnapshot:
        current = self.store.get(schedule_id)
        config = current.config.model_copy(update={"enabled": False})
        return self.store.update_config(schedule_id, config, next_run_at=None)

    def run_now(self, schedule_id: str) -> dict[str, Any]:
        snapshot = self.store.get(schedule_id)
        return self._submit(snapshot, due_at=self.now(), manual=True)

    def runs(self, schedule_id: str) -> dict[str, list[dict[str, Any]]]:
        self.store.get(schedule_id)
        return {"runs": [run.to_dict() for run in self.store.runs(schedule_id)]}

    def tick(self) -> None:
        now = self.now()
        for snapshot in self.store.due(now):
            self._submit(snapshot, due_at=snapshot.next_run_at or now, manual=False)

    def _submit(self, snapshot: DataScheduleSnapshot, *, due_at: datetime, manual: bool) -> dict[str, Any]:
        triggered_at = self.now()
        try:
            if not manual and self._should_skip_for_overlap(snapshot):
                next_run_at = compute_next_run_at(
                    snapshot.config,
                    now=triggered_at,
                    run_count=snapshot.run_count,
                )
                self.store.record_run(
                    schedule_id=snapshot.schedule_id,
                    due_at=due_at,
                    triggered_at=triggered_at,
                    status="skipped",
                    job_id=snapshot.last_job_id,
                    error="Previous scheduled job is still running",
                )
                self.store.update_state(
                    snapshot.schedule_id,
                    enabled=snapshot.enabled if next_run_at is not None else False,
                    status="enabled" if next_run_at is not None else "completed",
                    run_count=snapshot.run_count,
                    next_run_at=next_run_at,
                    last_run_at=triggered_at,
                    last_job_id=snapshot.last_job_id,
                    last_error=None,
                )
                return {
                    "status": "skipped",
                    "job_id": snapshot.last_job_id,
                    "reason": "Previous scheduled job is still running",
                }
            payload = build_job_payload(snapshot.config, self.server_config, now=triggered_at)
            job = self.submit_job(payload)
            next_count = snapshot.run_count + 1
            next_run_at = None if manual else compute_next_run_at(
                snapshot.config,
                now=triggered_at,
                run_count=next_count,
            )
            status = "completed" if next_run_at is None and not manual else ("enabled" if snapshot.enabled else "disabled")
            self.store.record_run(
                schedule_id=snapshot.schedule_id,
                due_at=due_at,
                triggered_at=triggered_at,
                status="submitted",
                job_id=job.job_id,
                error=None,
            )
            self.store.update_state(
                snapshot.schedule_id,
                enabled=snapshot.enabled if next_run_at is not None else False,
                status=status,
                run_count=next_count,
                next_run_at=next_run_at,
                last_run_at=triggered_at,
                last_job_id=job.job_id,
                last_error=None,
            )
            return job.to_dict() if hasattr(job, "to_dict") else {"job_id": job.job_id, "status": job.status}
        except Exception as exc:
            self.store.record_run(
                schedule_id=snapshot.schedule_id,
                due_at=due_at,
                triggered_at=triggered_at,
                status="failed",
                job_id=None,
                error=str(exc),
            )
            next_run_at = compute_next_run_at(snapshot.config, now=triggered_at, run_count=snapshot.run_count)
            self.store.update_state(
                snapshot.schedule_id,
                enabled=snapshot.enabled,
                status="error",
                run_count=snapshot.run_count,
                next_run_at=next_run_at,
                last_run_at=triggered_at,
                last_job_id=snapshot.last_job_id,
                last_error=str(exc),
            )
            raise

    def _should_skip_for_overlap(self, snapshot: DataScheduleSnapshot) -> bool:
        if snapshot.config.overlap_policy != "skip":
            return False
        if self.get_job is None or snapshot.last_job_id is None:
            return False
        try:
            job = self.get_job(snapshot.last_job_id)
        except ValueError:
            return False
        status = job.get("status") if isinstance(job, dict) else getattr(job, "status", None)
        return status in {"submitted", "running"}

    def _source_options(self, source) -> dict[str, Any]:
        source_name, exchange = _source_and_exchange(source.catalog_source)
        defaults = ["1d"] if source.source_id == "a_share" else ["1d", "4h", "1h", "30m", "15m", "5m", "1m"]
        return {
            "source_id": source.source_id,
            "source_label": source.source_label,
            "asset_class": source.asset_class,
            "default_source": source_name,
            "default_exchange": exchange,
            "default_adjust": source.adjust,
            "default_frequencies": defaults,
        }


class DataSourceScheduler:
    def __init__(self, *, service: DataSourceScheduleService, poll_seconds: float) -> None:
        self.service = service
        self.poll_seconds = poll_seconds
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def tick(self) -> None:
        self.service.tick()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            finally:
                self._stop.wait(self.poll_seconds)


def _deep_update(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value
```

- [ ] **Step 4: Run tests to verify Task 3 passes**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source/test_schedules.py -q
```

Expected: PASS for model, store, service, and scheduler tick tests.

- [ ] **Step 5: Commit Task 3**

```bash
git add backtest/data_source/schedules.py tests/data_source/test_schedules.py
git commit -m "feat: add data source schedule service"
```

## Task 4: API Facade Schedule Methods

**Files:**
- Modify: `backtest/data_source/api.py`
- Modify: `backtest/data_source/__init__.py`
- Test: `tests/data_source/test_api.py`

- [ ] **Step 1: Add failing API facade tests**

Append this test to `tests/data_source/test_api.py`:

```python
from backtest.data_source.schedules import DataSourceScheduleService, DataSourceScheduleStore


def test_api_exposes_schedule_service_methods(tmp_path: Path):
    api = _api(tmp_path)
    submitted = []
    service = DataSourceScheduleService(
        store=DataSourceScheduleStore(
            tmp_path / "schedules.sqlite",
            now=lambda: datetime(2026, 5, 18, 9, 0, 0),
        ),
        server_config=api.config,
        submit_job=lambda payload: submitted.append(payload) or api.submit_job(payload),
        get_job=api.job,
        now=lambda: datetime(2026, 5, 18, 9, 0, 0),
    )
    api.schedule_service = service

    options = api.schedule_options()
    created = api.create_schedule(
        {
            "name": "api-schedule",
            "trigger": {"type": "once", "run_at": "2026-05-18T09:00:00+08:00"},
            "job": {
                "source_id": "a_share",
                "symbols": ["000001.SZ"],
                "frequencies": ["1d"],
                "date_range": {
                    "type": "fixed",
                    "start_date": "2025-01-01",
                    "end_date": "2025-01-03",
                },
            },
        }
    )
    enabled = api.enable_schedule(created["schedule_id"])
    job = api.run_schedule_now(created["schedule_id"])

    assert options["trigger_types"] == ["once", "interval", "daily", "weekly"]
    assert created["name"] == "api-schedule"
    assert enabled["enabled"] is True
    assert job["status"] == "success"
    assert api.schedule_runs(created["schedule_id"])["runs"][0]["status"] == "submitted"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source/test_api.py -q
```

Expected: FAIL with `AttributeError` for `schedule_options`.

- [ ] **Step 3: Add API facade delegation**

Modify `backtest/data_source/api.py`:

```python
from backtest.data_source.schedules import DataSourceScheduleService
```

Update `DataSourceApi.__init__`:

```python
        self.schedule_service: DataSourceScheduleService | None = None
```

Add methods to `DataSourceApi`:

```python
    def schedule_options(self) -> dict[str, Any]:
        return self._schedules().options()

    def schedules(self) -> dict[str, list[dict[str, Any]]]:
        return self._schedules().list()

    def schedule(self, schedule_id: str) -> dict[str, Any]:
        return self._schedules().get(schedule_id).to_dict()

    def create_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._schedules().create(payload).to_dict()

    def update_schedule(self, schedule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._schedules().update(schedule_id, payload).to_dict()

    def delete_schedule(self, schedule_id: str) -> dict[str, str]:
        return self._schedules().delete(schedule_id)

    def enable_schedule(self, schedule_id: str) -> dict[str, Any]:
        return self._schedules().enable(schedule_id).to_dict()

    def disable_schedule(self, schedule_id: str) -> dict[str, Any]:
        return self._schedules().disable(schedule_id).to_dict()

    def run_schedule_now(self, schedule_id: str) -> dict[str, Any]:
        return self._schedules().run_now(schedule_id)

    def schedule_runs(self, schedule_id: str) -> dict[str, list[dict[str, Any]]]:
        return self._schedules().runs(schedule_id)

    def _schedules(self) -> DataSourceScheduleService:
        if self.schedule_service is None:
            raise ValueError("Scheduler is not configured")
        return self.schedule_service
```

Modify `backtest/data_source/__init__.py` to export:

```python
from backtest.data_source.schedules import (
    DataScheduleConfig,
    DataScheduleRunSnapshot,
    DataScheduleSnapshot,
    DataSourceScheduleService,
    DataSourceScheduleStore,
    DataSourceScheduler,
)
```

Add those names to `__all__`.

- [ ] **Step 4: Run API tests**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source/test_api.py tests/data_source/test_schedules.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```bash
git add backtest/data_source/api.py backtest/data_source/__init__.py tests/data_source/test_api.py
git commit -m "feat: expose schedule facade methods"
```

## Task 5: HTTP Schedule Routes

**Files:**
- Modify: `backtest/data_source/server.py`
- Test: `tests/data_source/test_server.py`

- [ ] **Step 1: Add failing HTTP route tests**

Append this test to `tests/data_source/test_server.py`:

```python
from backtest.data_source.schedules import DataSourceScheduleService, DataSourceScheduleStore


def test_schedule_http_routes(tmp_path: Path):
    api = _api(tmp_path)
    api.schedule_service = DataSourceScheduleService(
        store=DataSourceScheduleStore(
            tmp_path / "schedules.sqlite",
            now=lambda: datetime(2026, 5, 18, 9, 0, 0),
        ),
        server_config=api.config,
        submit_job=api.submit_job,
        now=lambda: datetime(2026, 5, 18, 9, 0, 0),
    )
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_data_source_handler(api))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, _, options = _json_request(base_url, "/api/data/schedule-options")
        _, _, created = _json_request(
            base_url,
            "/api/data/schedules",
            method="POST",
            payload={
                "name": "server-schedule",
                "trigger": {"type": "once", "run_at": "2026-05-18T09:00:00+08:00"},
                "job": {
                    "source_id": "a_share",
                    "symbols": ["000001.SZ"],
                    "frequencies": ["1d"],
                    "date_range": {
                        "type": "fixed",
                        "start_date": "2025-01-01",
                        "end_date": "2025-01-02",
                    },
                },
            },
        )
        _, _, schedules = _json_request(base_url, "/api/data/schedules")
        _, _, enabled = _json_request(base_url, f"/api/data/schedules/{created['schedule_id']}/enable", method="POST")
        _, _, updated = _json_request(
            base_url,
            f"/api/data/schedules/{created['schedule_id']}",
            method="PATCH",
            payload={"job": {"symbols": ["000002.SZ"]}},
        )
        _, _, job = _json_request(base_url, f"/api/data/schedules/{created['schedule_id']}/run-now", method="POST")
        _, _, runs = _json_request(base_url, f"/api/data/schedules/{created['schedule_id']}/runs")
        _, _, disabled = _json_request(base_url, f"/api/data/schedules/{created['schedule_id']}/disable", method="POST")

        assert "interval" in options["trigger_types"]
        assert schedules["schedules"][0]["schedule_id"] == created["schedule_id"]
        assert enabled["enabled"] is True
        assert updated["config"]["job"]["symbols"] == ["000002.SZ"]
        assert job["status"] == "success"
        assert runs["runs"][0]["status"] == "submitted"
        assert disabled["enabled"] is False
    finally:
        server.shutdown()
        server.server_close()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source/test_server.py::test_schedule_http_routes -q
```

Expected: FAIL with HTTP 404 for `/api/data/schedule-options`.

- [ ] **Step 3: Add HTTP method and route handling**

Modify `backtest/data_source/server.py`:

```python
        def do_PATCH(self) -> None:
            if not self._is_authorized():
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
                return
            parsed = urlparse(self.path)
            try:
                if parsed.path.startswith("/api/data/schedules/"):
                    schedule_id = parsed.path.rsplit("/", 1)[-1]
                    self._send_json(200, api.update_schedule(schedule_id, self._read_json()))
                else:
                    self._send_json(404, {"error": "Not found"})
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except json.JSONDecodeError as exc:
                self._send_json(400, {"error": str(exc)})
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
```

Add GET routes inside `do_GET` before the `/api/data/jobs` branch:

```python
                elif parsed.path == "/api/data/schedule-options":
                    self._send_json(200, api.schedule_options())
                elif parsed.path == "/api/data/schedules":
                    self._send_json(200, api.schedules())
                elif parsed.path.endswith("/runs") and parsed.path.startswith("/api/data/schedules/"):
                    schedule_id = parsed.path.removeprefix("/api/data/schedules/").removesuffix("/runs").strip("/")
                    self._send_json(200, api.schedule_runs(schedule_id))
                elif parsed.path.startswith("/api/data/schedules/"):
                    self._send_json(200, api.schedule(parsed.path.rsplit("/", 1)[-1]))
```

Add POST routes inside `do_POST` before the `/api/data/jobs` branch:

```python
                if parsed.path == "/api/data/schedules":
                    self._send_json(200, api.create_schedule(self._read_json()))
                elif parsed.path.endswith("/enable") and parsed.path.startswith("/api/data/schedules/"):
                    schedule_id = parsed.path.removeprefix("/api/data/schedules/").removesuffix("/enable").strip("/")
                    self._send_json(200, api.enable_schedule(schedule_id))
                elif parsed.path.endswith("/disable") and parsed.path.startswith("/api/data/schedules/"):
                    schedule_id = parsed.path.removeprefix("/api/data/schedules/").removesuffix("/disable").strip("/")
                    self._send_json(200, api.disable_schedule(schedule_id))
                elif parsed.path.endswith("/run-now") and parsed.path.startswith("/api/data/schedules/"):
                    schedule_id = parsed.path.removeprefix("/api/data/schedules/").removesuffix("/run-now").strip("/")
                    self._send_json(200, api.run_schedule_now(schedule_id))
```

Add `PATCH` to CORS:

```python
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
```

- [ ] **Step 4: Run HTTP tests**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source/test_server.py tests/data_source/test_api.py tests/data_source/test_schedules.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

```bash
git add backtest/data_source/server.py tests/data_source/test_server.py
git commit -m "feat: add schedule HTTP routes"
```

## Task 6: Data Source Config And CLI Wiring

**Files:**
- Modify: `backtest/data_source/config.py`
- Modify: `backtest/cli/data_source.py`
- Test: `tests/test_cli_commands.py`

- [ ] **Step 1: Add failing CLI wiring test**

Update `tests/test_cli_commands.py::test_data_source_serve_cli_passes_server_options` to include the new flags:

```python
            "--schedule-db",
            str(tmp_path / "schedules.sqlite"),
            "--scheduler-poll-seconds",
            "2",
            "--no-scheduler",
```

Add assertions:

```python
    assert captured["api"].config.schedule_db_path == tmp_path / "schedules.sqlite"
    assert captured["api"].config.scheduler_poll_seconds == 2
    assert captured["api"].schedule_service is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --with pytest python -m pytest tests/test_cli_commands.py::test_data_source_serve_cli_passes_server_options -q
```

Expected: FAIL because the CLI does not accept `--schedule-db`.

- [ ] **Step 3: Add config fields**

Modify `backtest/data_source/config.py`:

```python
from dataclasses import dataclass
from pathlib import Path
```

Extend `DataSourceServerConfig`:

```python
    schedule_db_path: Path = Path("data/data_source_schedules.sqlite")
    scheduler_poll_seconds: float = 5.0
```

Add validation to `__post_init__`:

```python
        if self.scheduler_poll_seconds <= 0:
            raise ValueError("scheduler_poll_seconds must be greater than 0")
        object.__setattr__(self, "schedule_db_path", Path(self.schedule_db_path))
```

- [ ] **Step 4: Wire CLI service and optional scheduler**

Modify imports in `backtest/cli/data_source.py`:

```python
from backtest.data_source.schedules import (
    DataSourceScheduleService,
    DataSourceScheduleStore,
    DataSourceScheduler,
)
```

Add Typer options to `serve()`:

```python
    schedule_db: Path = typer.Option(
        Path("data/data_source_schedules.sqlite"),
        "--schedule-db",
        help="SQLite database for data-source schedule definitions and run history",
    ),
    scheduler_poll_seconds: float = typer.Option(
        5.0,
        "--scheduler-poll-seconds",
        min=0.1,
        help="How often the in-process scheduler scans for due schedules",
    ),
    scheduler_enabled: bool = typer.Option(
        True,
        "--scheduler/--no-scheduler",
        help="Start the in-process scheduler loop",
    ),
```

Pass values into `DataSourceServerConfig`:

```python
            schedule_db_path=schedule_db,
            scheduler_poll_seconds=scheduler_poll_seconds,
```

After constructing `api`, attach schedule service:

```python
        schedule_service = DataSourceScheduleService(
            store=DataSourceScheduleStore(schedule_db),
            server_config=config,
            submit_job=api.submit_job,
            get_job=api.job,
        )
        api.schedule_service = schedule_service
        scheduler = DataSourceScheduler(
            service=schedule_service,
            poll_seconds=scheduler_poll_seconds,
        )
        if scheduler_enabled:
            scheduler.start()
```

Keep `scheduler` in local scope before `serve_data_source_api()` so the object
is not garbage-collected while the server runs.

- [ ] **Step 5: Run CLI tests**

Run:

```bash
uv run --with pytest python -m pytest tests/test_cli_commands.py::test_data_source_serve_cli_passes_server_options -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 6**

```bash
git add backtest/data_source/config.py backtest/cli/data_source.py tests/test_cli_commands.py
git commit -m "feat: wire scheduler into data source CLI"
```

## Task 7: Schedule Delete Route And Error Semantics

**Files:**
- Modify: `backtest/data_source/server.py`
- Test: `tests/data_source/test_server.py`

- [ ] **Step 1: Add failing delete and error tests**

Append this test to `tests/data_source/test_server.py`:

```python
def test_schedule_delete_and_invalid_route_errors(tmp_path: Path):
    api = _api(tmp_path)
    api.schedule_service = DataSourceScheduleService(
        store=DataSourceScheduleStore(tmp_path / "schedules.sqlite"),
        server_config=api.config,
        submit_job=api.submit_job,
    )
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_data_source_handler(api))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, _, created = _json_request(
            base_url,
            "/api/data/schedules",
            method="POST",
            payload={
                "name": "delete-me",
                "trigger": {"type": "once", "run_at": "2026-05-18T09:00:00+08:00"},
                "job": {
                    "source_id": "a_share",
                    "symbols": ["000001.SZ"],
                    "frequencies": ["1d"],
                    "date_range": {
                        "type": "fixed",
                        "start_date": "2025-01-01",
                        "end_date": "2025-01-02",
                    },
                },
            },
        )
        _, _, deleted = _json_request(
            base_url,
            f"/api/data/schedules/{created['schedule_id']}",
            method="DELETE",
        )
        assert deleted == {"deleted": created["schedule_id"]}

        try:
            _json_request(base_url, f"/api/data/schedules/{created['schedule_id']}")
        except HTTPError as exc:
            assert exc.code == 400
            assert "Unknown schedule" in json.loads(exc.read().decode("utf-8"))["error"]
    finally:
        server.shutdown()
        server.server_close()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source/test_server.py::test_schedule_delete_and_invalid_route_errors -q
```

Expected: FAIL because `DELETE` is not implemented.

- [ ] **Step 3: Implement DELETE**

Add to `backtest/data_source/server.py`:

```python
        def do_DELETE(self) -> None:
            if not self._is_authorized():
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
                return
            parsed = urlparse(self.path)
            try:
                if parsed.path.startswith("/api/data/schedules/"):
                    self._send_json(200, api.delete_schedule(parsed.path.rsplit("/", 1)[-1]))
                else:
                    self._send_json(404, {"error": "Not found"})
            except ValueError as exc:
                self._send_json(400, {"error": str(exc)})
            except Exception as exc:
                self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
```

Update CORS:

```python
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, DELETE, OPTIONS")
```

- [ ] **Step 4: Run data-source test suite**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 7**

```bash
git add backtest/data_source/server.py tests/data_source/test_server.py
git commit -m "feat: support deleting data source schedules"
```

## Task 8: Agent Skill And Operations Documentation

**Files:**
- Modify: `.codex/skills/backtest-im-agent-api/SKILL.md`
- Modify: `.codex/skills/backtest-im-agent-api/references/data-source-http-api.md`
- Modify: `.codex/skills/backtest-im-agent-api/references/dialogue-flows.md`
- Modify: `.codex/skills/backtest-data-source-ops/SKILL.md`
- Modify: `.codex/skills/backtest-data-source-ops/references/data-job-fields.md`
- Modify: `docs/market-data-operations.md`
- Modify: `docs/remote-workbench-deployment.md`

- [ ] **Step 1: Add failing documentation checks**

Run:

```bash
rg -n "schedule-options|/api/data/schedules|run-now|enable|disable" .codex/skills docs/market-data-operations.md docs/remote-workbench-deployment.md
```

Expected: FAIL to find schedule endpoint documentation before this task is implemented.

- [ ] **Step 2: Update IM Agent skill authority**

In `.codex/skills/backtest-im-agent-api/SKILL.md`, extend the trigger paragraph to include:

```markdown
When the user mentions scheduled crawl jobs, recurring data fetch, periodic tasks, 定时任务, 周期任务, 循环执行, 打开任务, 关闭任务, or run counts for market-data crawling, use this skill and manage schedules through the data-source HTTP API.
```

Add read endpoints:

```markdown
- `GET /api/data/schedule-options`
- `GET /api/data/schedules`
- `GET /api/data/schedules/<schedule_id>`
- `GET /api/data/schedules/<schedule_id>/runs`
```

Add write endpoints that require confirmation:

```markdown
- `POST /api/data/schedules`
- `PATCH /api/data/schedules/<schedule_id>`
- `DELETE /api/data/schedules/<schedule_id>`
- `POST /api/data/schedules/<schedule_id>/enable`
- `POST /api/data/schedules/<schedule_id>/disable`
- `POST /api/data/schedules/<schedule_id>/run-now`
```

- [ ] **Step 3: Update HTTP API reference**

Add this section to `.codex/skills/backtest-im-agent-api/references/data-source-http-api.md`:

```markdown
## Schedule Management

Read endpoints:

```text
GET /api/data/schedule-options
GET /api/data/schedules
GET /api/data/schedules/<schedule_id>
GET /api/data/schedules/<schedule_id>/runs
```

Write endpoints:

```text
POST   /api/data/schedules
PATCH  /api/data/schedules/<schedule_id>
DELETE /api/data/schedules/<schedule_id>
POST   /api/data/schedules/<schedule_id>/enable
POST   /api/data/schedules/<schedule_id>/disable
POST   /api/data/schedules/<schedule_id>/run-now
```

Write endpoints require explicit user confirmation. Use
`GET /api/data/schedule-options` before constructing a schedule when source
defaults, frequencies, trigger types, repeat modes, or date range types are
unknown.
```

- [ ] **Step 4: Update dialogue flow**

Add this section to `.codex/skills/backtest-im-agent-api/references/dialogue-flows.md`:

```markdown
## Schedule Management

Flow:

1. Ensure an API client is configured. Run access discovery only if the client is missing, unvalidated, changed, or currently failing.
2. Call `GET /api/data/schedule-options` when supported fields or source defaults are unknown.
3. Identify trigger time, repeat policy, symbols, frequencies, source, date range, retry policy, and whether the schedule should start enabled.
4. Ask one concise follow-up if a required field remains ambiguous.
5. Show the final schedule summary including trigger, repeat count or stop condition, source, symbols, frequencies, date range, and enabled state.
6. Call schedule write endpoints only after explicit confirmation.
7. Return `schedule_id`, enabled state, `next_run_at`, and the next status-check action.

For enable, disable, delete, and run-now requests, confirm the target schedule id or name before writing.
```

- [ ] **Step 5: Update operations docs**

Add examples to `docs/market-data-operations.md` and `docs/remote-workbench-deployment.md`:

```markdown
## Scheduled Data Jobs

Create a disabled schedule:

```bash
curl -sS http://127.0.0.1:8768/api/data/schedules \
  -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "bitget-hourly",
    "trigger": {"type": "interval", "every": 1, "unit": "hours", "timezone": "Asia/Shanghai"},
    "repeat": {"mode": "count", "count": 24},
    "job": {
      "source_id": "bitget",
      "symbols": ["BTC/USDT", "ETH/USDT"],
      "frequencies": ["1h"],
      "date_range": {"type": "last_n_days", "days": 7}
    },
    "overlap_policy": "skip"
  }'
```

Enable it after review:

```bash
curl -sS -X POST http://127.0.0.1:8768/api/data/schedules/<schedule_id>/enable \
  -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN"
```
```

- [ ] **Step 6: Verify documentation mentions schedule API**

Run:

```bash
rg -n "schedule-options|/api/data/schedules|run-now|enable|disable" .codex/skills docs/market-data-operations.md docs/remote-workbench-deployment.md
```

Expected: PASS with matches in both skill references and docs.

- [ ] **Step 7: Commit Task 8**

```bash
git add .codex/skills/backtest-im-agent-api .codex/skills/backtest-data-source-ops docs/market-data-operations.md docs/remote-workbench-deployment.md
git commit -m "docs: document data source schedule management"
```

## Task 9: Final Verification

**Files:**
- No new files.
- Verify all changed files from Tasks 1-8.

- [ ] **Step 1: Run focused data-source tests**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source tests/test_cli_commands.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run:

```bash
uv run --with pytest python -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Verify data-source serve help includes scheduler flags**

Run:

```bash
uv run backtest data-source serve --help
```

Expected: output includes `--schedule-db`, `--scheduler-poll-seconds`, and `--no-scheduler`.

- [ ] **Step 4: Verify no placeholder language remains in scheduler files**

Run:

```bash
rg -n "TB[D]|TO[D]O|implement late[r]|fill in detail[s]|add appropriat[e]|handle edge case[s]|Similar to Tas[k]" backtest/data_source tests/data_source .codex/skills docs/market-data-operations.md docs/remote-workbench-deployment.md
```

Expected: no matches in files changed for this feature.

- [ ] **Step 5: Review git diff**

Run:

```bash
git diff --stat main...HEAD
git diff -- backtest/data_source/schedules.py backtest/data_source/api.py backtest/data_source/server.py backtest/cli/data_source.py
```

Expected: changes are limited to scheduler models/store/service, API/HTTP/CLI wiring, tests, and docs.

- [ ] **Step 6: Commit any final verification-only fixes**

If verification required a small fix, commit it:

```bash
git add backtest tests .codex/skills docs
git commit -m "test: verify data source scheduler"
```

If no fix was required, no commit is needed for this step.
