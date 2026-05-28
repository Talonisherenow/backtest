from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

from backtest.core.enums import AdjustMode, Frequency
from backtest.core.symbols import normalize_symbol
from backtest.data.jobs import RetryConfig
from backtest.data_source.config import DataSourceServerConfig


WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
DEFAULT_TIMEZONE = "Asia/Shanghai"
RangeUnit = Literal["minutes", "hours", "days"]
LOGGER = logging.getLogger(__name__)


class ScheduleTargetConfig(BaseModel):
    mode: Literal["symbols", "tag"]
    instrument_ids: list[str] = Field(default_factory=list)
    tag_id: str | None = None
    resolution: Literal["dynamic"] = "dynamic"

    @field_validator("instrument_ids")
    @classmethod
    def normalize_instrument_ids(cls, value: list[str]) -> list[str]:
        return [str(item).strip().upper() for item in value if str(item).strip()]

    @field_validator("tag_id")
    @classmethod
    def clean_tag_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_target(self) -> "ScheduleTargetConfig":
        if self.mode == "symbols" and not self.instrument_ids:
            raise ValueError("instrument_ids are required for symbols target")
        if self.mode == "tag" and self.tag_id is None:
            raise ValueError("tag_id is required for tag target")
        return self


class TriggerConfig(BaseModel):
    type: Literal["once", "interval", "daily", "weekly"]
    timezone: str = DEFAULT_TIMEZONE
    run_at: datetime | None = None
    start_at: datetime | None = None
    every: int | None = Field(default=None, ge=1)
    unit: Literal["seconds", "minutes", "hours", "days"] | None = None
    time: str | None = None
    days_of_week: list[str] = Field(default_factory=list)
    execution_delay_seconds: float = Field(default=0.0, ge=0)

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
    start_at: datetime | None = None
    end_at: datetime | None = None
    days: int | None = Field(default=None, ge=1)
    end_offset_days: int = Field(default=0, ge=0)
    lookback_value: int | None = Field(default=None, ge=1)
    lookback_unit: RangeUnit | None = None
    end_offset_value: int | None = Field(default=None, ge=0)
    end_offset_unit: RangeUnit | None = None

    @model_validator(mode="after")
    def validate_range(self) -> "DateRangeConfig":
        if self.type == "fixed":
            has_dates = self.start_date is not None or self.end_date is not None
            has_times = self.start_at is not None or self.end_at is not None
            if has_times:
                if self.start_at is None or self.end_at is None:
                    raise ValueError("start_at and end_at are required for fixed date_range")
                if self.end_at < self.start_at:
                    raise ValueError("end_at must be on or after start_at")
            if has_dates:
                if self.start_date is None or self.end_date is None:
                    raise ValueError("start_date and end_date are required for fixed date_range")
                if self.end_date < self.start_date:
                    raise ValueError("end_date must be on or after start_date")
            if not has_dates and not has_times:
                raise ValueError(
                    "start_date/end_date or start_at/end_at are required for fixed date_range"
                )
            if has_times and not has_dates:
                self.start_date = self.start_at.date() if self.start_at else None
                self.end_date = self.end_at.date() if self.end_at else None
            return self
        if self.lookback_value is None and self.days is None:
            raise ValueError("days or lookback_value is required for last_n_days date_range")
        if self.lookback_value is None:
            self.lookback_value = self.days
        if self.lookback_unit is None:
            self.lookback_unit = "days"
        if self.days is None and self.lookback_unit == "days":
            self.days = self.lookback_value
        if self.end_offset_value is None:
            self.end_offset_value = self.end_offset_days
        if self.end_offset_unit is None:
            self.end_offset_unit = "days"
        if self.end_offset_unit == "days":
            self.end_offset_days = self.end_offset_value or 0
        if self.lookback_unit == "days" and self.days is None:
            self.days = self.lookback_value
        if self.days is not None and self.days < 1:
            raise ValueError("days must be greater than or equal to 1")
        if self.end_offset_days < 0:
            raise ValueError("end_offset_days must be greater than or equal to 0")
        return self


class ScheduleJobTemplate(BaseModel):
    source_id: str
    symbols: list[str] = Field(default_factory=list)
    target: ScheduleTargetConfig | None = None
    frequencies: list[Frequency]
    date_range: DateRangeConfig
    source: str | None = None
    exchange: str | None = None
    adjust: AdjustMode | None = None
    page_delay_seconds: float = Field(default=0.0, ge=0)
    refresh_existing: bool = True
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
        return [normalize_symbol(symbol) for symbol in value]

    @field_validator("frequencies")
    @classmethod
    def validate_frequencies(cls, value: list[Frequency]) -> list[Frequency]:
        if not value:
            raise ValueError("frequencies must not be empty")
        return value

    @model_validator(mode="after")
    def validate_symbols_or_target(self) -> "ScheduleJobTemplate":
        if not self.symbols and self.target is None:
            raise ValueError("symbols or target is required")
        return self


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


def compute_next_run_at(
    schedule: DataScheduleConfig,
    *,
    now: datetime,
    run_count: int,
    after: bool = False,
) -> datetime | None:
    trigger = schedule.trigger
    zone = ZoneInfo(trigger.timezone)
    local_now = _aware(now, zone)
    if _repeat_exhausted(schedule, now=local_now, run_count=run_count):
        return None

    if trigger.type == "once":
        candidate = _aware(trigger.run_at, zone)
        if run_count > 0 or after:
            return None
        return _with_execution_delay(candidate, trigger) if candidate >= local_now else None
    if trigger.type == "interval":
        candidate = _next_interval(trigger, local_now, after=after)
    elif trigger.type == "daily":
        wall_clock_now = _wall_clock_floor(trigger, local_now)
        candidate = _next_daily(
            trigger,
            wall_clock_now,
            after=after and wall_clock_now == local_now,
        )
    else:
        wall_clock_now = _wall_clock_floor(trigger, local_now)
        candidate = _next_weekly(
            trigger,
            wall_clock_now,
            after=after and wall_clock_now == local_now,
        )

    if schedule.repeat.mode == "until" and schedule.repeat.until is not None:
        if candidate > _aware(schedule.repeat.until, zone):
            return None
    return _with_execution_delay(candidate, trigger)


def build_job_payload(
    schedule: DataScheduleConfig,
    server_config: DataSourceServerConfig,
    *,
    now: datetime,
    resolve_symbols: Callable[[str, ScheduleTargetConfig | None, list[str]], list[str]] | None = None,
) -> dict[str, Any]:
    spec = server_config.source(schedule.job.source_id)
    source, exchange = _source_and_exchange(spec.catalog_source)
    adjust = schedule.job.adjust.value if schedule.job.adjust else spec.adjust
    if schedule.job.source is not None and schedule.job.source != source:
        raise ValueError(f"source override conflicts with source_id={spec.source_id}")
    if schedule.job.exchange is not None and schedule.job.exchange != exchange:
        raise ValueError(f"exchange override conflicts with source_id={spec.source_id}")
    if schedule.job.adjust is not None and adjust != spec.adjust:
        raise ValueError(f"adjust override conflicts with source_id={spec.source_id}")
    start_date, end_date = _date_range(schedule.job.date_range, now=now)
    symbols = _resolved_job_symbols(schedule.job, resolve_symbols)
    safe_name = _slug(schedule.name)
    return {
        "name": f"scheduled-{safe_name}",
        "source": source,
        "exchange": exchange,
        "symbols": symbols,
        "frequencies": [frequency.value for frequency in schedule.job.frequencies],
        "adjust": adjust,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "bars_root": str(spec.bars_root),
        "metadata": str(spec.metadata_path),
        "output_dir": str(Path("runs/data_jobs") / safe_name),
        "page_delay_seconds": schedule.job.page_delay_seconds,
        "refresh_existing": schedule.job.refresh_existing,
        "retry": schedule.job.retry.model_dump(mode="json"),
    }


def _resolved_job_symbols(
    job: ScheduleJobTemplate,
    resolve_symbols: Callable[[str, ScheduleTargetConfig | None, list[str]], list[str]] | None,
) -> list[str]:
    if job.target is None:
        return job.symbols
    if resolve_symbols is None:
        raise ValueError("schedule target resolver is required")
    symbols = [normalize_symbol(symbol) for symbol in resolve_symbols(job.source_id, job.target, job.symbols)]
    if not symbols:
        raise ValueError("schedule target resolved no symbols")
    return symbols


class DataSourceScheduleStore:
    def __init__(
        self,
        path: str | Path,
        *,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
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
        with self._lock:
            schedule_id = self._unique_id("data_schedules", "schedule_id", now, config.name)
            status = "enabled" if config.enabled else "disabled"
            with self.connect() as conn:
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
                WHERE enabled = 1 AND next_run_at IS NOT NULL
                ORDER BY next_run_at, schedule_id
                """,
            ).fetchall()
        snapshots = [self._snapshot(row) for row in rows]
        return [
            snapshot
            for snapshot in snapshots
            if snapshot.next_run_at is not None and _datetime_lte(snapshot.next_run_at, now)
        ]

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
        with self._lock:
            run_id = self._unique_id(
                "data_schedule_runs",
                "run_id",
                triggered_at,
                schedule_id,
            )
            with self.connect() as conn:
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
        return self.run(run_id)

    def run(self, run_id: str) -> DataScheduleRunSnapshot:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM data_schedule_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown schedule run: {run_id}")
        return self._run_snapshot(row)

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
        base = f"{when:%Y%m%d%H%M%S}-{_slug(name)}"
        with self.connect() as conn:
            rows = conn.execute(f"SELECT {column} AS value FROM {table}").fetchall()
        existing = {row["value"] for row in rows}
        candidate = base
        counter = 2
        while candidate in existing:
            candidate = f"{base}-{counter}"
            counter += 1
        return candidate


class DataSourceScheduleService:
    def __init__(
        self,
        *,
        store: DataSourceScheduleStore,
        server_config: DataSourceServerConfig,
        submit_job: Callable[[dict[str, Any]], Any],
        get_job: Callable[[str], Any] | None = None,
        resolve_symbols: Callable[[str, ScheduleTargetConfig | None, list[str]], list[str]] | None = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.store = store
        self.server_config = server_config
        self.submit_job = submit_job
        self.get_job = get_job
        self.resolve_symbols = resolve_symbols
        self.now = now

    def options(self) -> dict[str, Any]:
        return {
            "timezone_default": DEFAULT_TIMEZONE,
            "trigger_types": ["once", "interval", "daily", "weekly"],
            "interval_units": ["seconds", "minutes", "hours", "days"],
            "execution_delay_units": ["seconds", "minutes", "hours"],
            "repeat_modes": ["forever", "count", "until"],
            "overlap_policies": ["skip", "allow"],
            "date_range_types": ["fixed", "last_n_days"],
            "range_units": ["minutes", "hours", "days"],
            "frequencies": _frequency_values(),
            "sources": [self._source_options(source) for source in self.server_config.sources],
            "example": {
                "name": "bitget-core-hourly",
                "enabled": False,
                "trigger": {
                    "type": "interval",
                    "every": 1,
                    "unit": "hours",
                    "start_at": "2026-05-20T09:00:00+08:00",
                    "timezone": DEFAULT_TIMEZONE,
                    "execution_delay_seconds": 60,
                },
                "repeat": {"mode": "count", "count": 24},
                "job": {
                    "source_id": "bitget",
                    "symbols": ["BTC/USDT"],
                    "frequencies": ["1h"],
                    "date_range": {
                        "type": "last_n_days",
                        "lookback_value": 7,
                        "lookback_unit": "days",
                    },
                    "refresh_existing": True,
                },
                "overlap_policy": "skip",
            },
        }

    def list(self) -> dict[str, list[dict[str, Any]]]:
        return {"schedules": [snapshot.to_dict() for snapshot in self.store.list()]}

    def get(self, schedule_id: str) -> DataScheduleSnapshot:
        return self.store.get(schedule_id)

    def create(self, payload: dict[str, Any]) -> DataScheduleSnapshot:
        config = DataScheduleConfig.model_validate(payload)
        self._validate_job(config)
        next_run_at = (
            compute_next_run_at(config, now=self.now(), run_count=0) if config.enabled else None
        )
        return self.store.create(config, next_run_at=next_run_at)

    def update(self, schedule_id: str, payload: dict[str, Any]) -> DataScheduleSnapshot:
        current = self.store.get(schedule_id)
        merged = current.config.model_dump(mode="json")
        _deep_update(merged, payload)
        config = DataScheduleConfig.model_validate(merged)
        self._validate_job(config)
        next_run_at = (
            compute_next_run_at(config, now=self.now(), run_count=current.run_count)
            if config.enabled
            else None
        )
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
            try:
                self._submit(snapshot, due_at=snapshot.next_run_at or now, manual=False)
            except Exception:
                continue

    def _submit(
        self,
        snapshot: DataScheduleSnapshot,
        *,
        due_at: datetime,
        manual: bool,
    ) -> dict[str, Any]:
        triggered_at = self.now()
        try:
            if not manual and self._should_skip_for_overlap(snapshot):
                return self._record_skipped(snapshot, due_at=due_at, triggered_at=triggered_at)

            payload = build_job_payload(
                snapshot.config,
                self.server_config,
                now=_job_payload_anchor(
                    snapshot.config,
                    due_at=due_at,
                    triggered_at=triggered_at,
                    manual=manual,
                ),
                resolve_symbols=self.resolve_symbols,
            )
            job = self.submit_job(payload)
            job_id = str(_value(job, "job_id"))
            next_count = snapshot.run_count + 1
            next_run_at = (
                compute_next_run_at(
                    snapshot.config,
                    now=triggered_at,
                    run_count=next_count,
                    after=True,
                )
                if snapshot.enabled
                else None
            )
            enabled = snapshot.enabled and next_run_at is not None
            status = "enabled" if enabled else ("completed" if snapshot.enabled else "disabled")
            self.store.record_run(
                schedule_id=snapshot.schedule_id,
                due_at=due_at,
                triggered_at=triggered_at,
                status="submitted",
                job_id=job_id,
                error=None,
            )
            self.store.update_state(
                snapshot.schedule_id,
                enabled=enabled,
                status=status,
                run_count=next_count,
                next_run_at=next_run_at,
                last_run_at=triggered_at,
                last_job_id=job_id,
                last_error=None,
            )
            return _job_to_dict(job)
        except Exception as exc:
            self.store.record_run(
                schedule_id=snapshot.schedule_id,
                due_at=due_at,
                triggered_at=triggered_at,
                status="failed",
                job_id=None,
                error=str(exc),
            )
            next_run_at = (
                compute_next_run_at(
                    snapshot.config,
                    now=triggered_at,
                    run_count=snapshot.run_count,
                    after=True,
                )
                if snapshot.enabled
                else None
            )
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

    def _record_skipped(
        self,
        snapshot: DataScheduleSnapshot,
        *,
        due_at: datetime,
        triggered_at: datetime,
    ) -> dict[str, Any]:
        next_run_at = compute_next_run_at(
            snapshot.config,
            now=triggered_at,
            run_count=snapshot.run_count,
            after=True,
        )
        enabled = snapshot.enabled and next_run_at is not None
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
            enabled=enabled,
            status="enabled" if enabled else "completed",
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

    def _should_skip_for_overlap(self, snapshot: DataScheduleSnapshot) -> bool:
        if snapshot.config.overlap_policy != "skip":
            return False
        if self.get_job is None or snapshot.last_job_id is None:
            return False
        try:
            job = self.get_job(snapshot.last_job_id)
        except ValueError:
            return False
        return _value(job, "status") in {"submitted", "running"}

    def _validate_job(self, config: DataScheduleConfig) -> None:
        build_job_payload(
            config,
            self.server_config,
            now=self.now(),
            resolve_symbols=self.resolve_symbols,
        )

    @staticmethod
    def _source_options(source) -> dict[str, Any]:
        source_name, exchange = _source_and_exchange(source.catalog_source)
        defaults = ["1d"] if source.source_id == "a_share" else _frequency_values()
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
            except Exception:
                LOGGER.exception("Data source scheduler tick failed")
            finally:
                self._stop.wait(self.poll_seconds)


def _repeat_exhausted(
    schedule: DataScheduleConfig,
    *,
    now: datetime,
    run_count: int,
) -> bool:
    if schedule.trigger.type == "once" and run_count >= 1:
        return True
    if schedule.repeat.mode == "count" and schedule.repeat.count is not None:
        return run_count >= schedule.repeat.count
    if schedule.repeat.mode == "until" and schedule.repeat.until is not None:
        return now > _aware(schedule.repeat.until, ZoneInfo(schedule.trigger.timezone))
    return False


def _aware(value: datetime | None, zone: ZoneInfo) -> datetime:
    if value is None:
        raise ValueError("datetime value is required")
    if value.tzinfo is None:
        return value.replace(tzinfo=zone)
    return value.astimezone(zone)


def _job_payload_anchor(
    schedule: DataScheduleConfig,
    *,
    due_at: datetime,
    triggered_at: datetime,
    manual: bool,
) -> datetime:
    if manual or schedule.trigger.execution_delay_seconds <= 0:
        return triggered_at
    zone = ZoneInfo(schedule.trigger.timezone)
    return _aware(due_at, zone) - timedelta(seconds=schedule.trigger.execution_delay_seconds)


def _with_execution_delay(candidate: datetime, trigger: TriggerConfig) -> datetime:
    if trigger.execution_delay_seconds <= 0:
        return candidate
    return candidate + timedelta(seconds=trigger.execution_delay_seconds)


def _next_interval(trigger: TriggerConfig, now: datetime, *, after: bool) -> datetime:
    start = _aware(trigger.start_at, now.tzinfo) if trigger.start_at else now
    delta = {
        "seconds": timedelta(seconds=trigger.every or 1),
        "minutes": timedelta(minutes=trigger.every or 1),
        "hours": timedelta(hours=trigger.every or 1),
        "days": timedelta(days=trigger.every or 1),
    }[trigger.unit or "hours"]
    if start > now or (start == now and not after):
        return start
    elapsed = now - start
    steps = int(elapsed.total_seconds() // delta.total_seconds()) + 1
    return start + delta * steps


def _wall_clock_floor(trigger: TriggerConfig, now: datetime) -> datetime:
    if trigger.start_at is None:
        return now
    start = _aware(trigger.start_at, now.tzinfo)
    return start if start > now else now


def _next_daily(trigger: TriggerConfig, now: datetime, *, after: bool) -> datetime:
    local_time = time.fromisoformat(trigger.time or "00:00")
    candidate = now.replace(
        hour=local_time.hour,
        minute=local_time.minute,
        second=local_time.second,
        microsecond=0,
    )
    if candidate < now or (after and candidate <= now):
        candidate = candidate + timedelta(days=1)
    return candidate


def _next_weekly(trigger: TriggerConfig, now: datetime, *, after: bool) -> datetime:
    local_time = time.fromisoformat(trigger.time or "00:00")
    allowed = {WEEKDAYS[item] for item in trigger.days_of_week}
    for offset in range(0, 8):
        candidate_date = now.date() + timedelta(days=offset)
        if candidate_date.weekday() not in allowed:
            continue
        candidate = datetime.combine(candidate_date, local_time, tzinfo=now.tzinfo)
        if candidate > now or (candidate == now and not after):
            return candidate
    raise ValueError("Unable to compute weekly next run")


def _date_range(config: DateRangeConfig, *, now: datetime) -> tuple[date, date]:
    start_at, end_at = _date_range_window(config, now=now)
    return start_at.date(), end_at.date()


def _date_range_window(config: DateRangeConfig, *, now: datetime) -> tuple[datetime, datetime]:
    zone = now.tzinfo or ZoneInfo(DEFAULT_TIMEZONE)
    if config.type == "fixed":
        if config.start_at is not None and config.end_at is not None:
            return _aware(config.start_at, zone), _aware(config.end_at, zone)
        if config.start_date is None or config.end_date is None:
            raise ValueError("fixed date_range requires start_date/end_date or start_at/end_at")
        return (
            datetime.combine(config.start_date, time.min, tzinfo=zone),
            datetime.combine(config.end_date, time.max, tzinfo=zone),
        )

    lookback_value = config.lookback_value or config.days or 1
    lookback_unit = config.lookback_unit or "days"
    end_offset_value = (
        config.end_offset_value
        if config.end_offset_value is not None
        else config.end_offset_days
    )
    end_offset_unit = config.end_offset_unit or "days"
    local_now = _aware(now, zone)

    if lookback_unit == "days" and end_offset_unit == "days":
        end_date = local_now.date() - timedelta(days=end_offset_value)
        start_date = end_date - timedelta(days=lookback_value - 1)
        return (
            datetime.combine(start_date, time.min, tzinfo=zone),
            datetime.combine(end_date, time.max, tzinfo=zone),
        )

    end_at = local_now - _range_delta(end_offset_value, end_offset_unit)
    start_at = end_at - _range_delta(lookback_value, lookback_unit)
    return start_at, end_at


def _range_delta(value: int, unit: RangeUnit) -> timedelta:
    if unit == "minutes":
        return timedelta(minutes=value)
    if unit == "hours":
        return timedelta(hours=value)
    return timedelta(days=value)


def _source_and_exchange(catalog_source: str) -> tuple[str, str | None]:
    if catalog_source.startswith("ccxt:"):
        return "ccxt", catalog_source.split(":", 1)[1]
    return catalog_source, None


def _deep_update(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def _parse_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _datetime_lte(left: datetime, right: datetime) -> bool:
    if left.tzinfo is None and right.tzinfo is None:
        return left <= right
    zone = ZoneInfo(DEFAULT_TIMEZONE)
    return _aware(left, zone) <= _aware(right, zone)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "schedule"


def _frequency_values() -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for frequency in Frequency:
        if frequency.value not in seen:
            seen.add(frequency.value)
            values.append(frequency.value)
    return values


def _value(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key)


def _job_to_dict(job: Any) -> dict[str, Any]:
    if hasattr(job, "to_dict"):
        return job.to_dict()
    if isinstance(job, dict):
        return dict(job)
    return {
        "job_id": _value(job, "job_id"),
        "status": _value(job, "status"),
    }
