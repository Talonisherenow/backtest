from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from backtest.core.enums import AdjustMode, Frequency
from backtest.core.symbols import normalize_symbol
from backtest.data.catalog import DataCatalog
from backtest.data.service import DataSyncService


class RetryConfig(BaseModel):
    max_attempts: int = Field(default=3, ge=1)
    request_delay_seconds: float = Field(default=0.0, ge=0)
    failure_cooldown_seconds: float = Field(default=0.0, ge=0)
    continue_on_error: bool = True


class DataSyncJobConfig(BaseModel):
    name: str
    source: str
    exchange: str | None = None
    symbols: list[str]
    frequencies: list[Frequency]
    adjust: AdjustMode = AdjustMode.QFQ
    start_date: date
    end_date: date
    bars_root: Path = Path("data/bars")
    metadata: Path = Path("data/metadata.sqlite")
    output_dir: Path = Path("runs/data_jobs")
    retry: RetryConfig = Field(default_factory=RetryConfig)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be empty")
        return normalized

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("source must not be empty")
        return normalized

    @field_validator("exchange")
    @classmethod
    def normalize_exchange(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None

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

    @model_validator(mode="after")
    def validate_job(self) -> "DataSyncJobConfig":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.source == "ccxt":
            if self.exchange is None:
                raise ValueError("exchange is required when source=ccxt")
            if self.adjust != AdjustMode.NONE:
                raise ValueError("source=ccxt requires adjust=none")
        return self

    @property
    def catalog_source(self) -> str:
        if self.source == "ccxt":
            return f"ccxt:{self.exchange}"
        return self.source


def load_data_sync_job_config(path: str | Path) -> DataSyncJobConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle)
    return DataSyncJobConfig.model_validate(data)


class JobItem(BaseModel):
    symbol: str
    frequency: Frequency
    adjust: AdjustMode
    start_date: date
    end_date: date
    source: str


class JobItemResult(BaseModel):
    job_name: str
    source: str
    exchange: str | None
    symbol: str
    frequency: Frequency
    adjust: AdjustMode
    start_date: date
    end_date: date
    status: str
    attempts: int
    rows: int = 0
    error: str | None = None
    started_at: datetime
    finished_at: datetime


class JobResult(BaseModel):
    name: str
    started_at: datetime
    finished_at: datetime | None = None
    items: list[JobItemResult] = Field(default_factory=list)

    @property
    def total_items(self) -> int:
        return len(self.items)

    @property
    def success_count(self) -> int:
        return sum(1 for item in self.items if item.status == "success")

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.items if item.status == "failed")

    @property
    def total_rows(self) -> int:
        return sum(item.rows for item in self.items)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([item.model_dump(mode="json") for item in self.items])

    def write(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        self.to_frame().to_csv(output_dir / "summary.csv", index=False)
        payload = self.model_dump(mode="json")
        (output_dir / "summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


class MarketDataJobRunner:
    def __init__(
        self,
        service: DataSyncService,
        catalog: DataCatalog,
        *,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.service = service
        self.catalog = catalog
        self.sleep = sleep
        self.now = now

    def run(self, config: DataSyncJobConfig) -> JobResult:
        result = JobResult(name=config.name, started_at=self.now())
        try:
            for item in self._items(config):
                item_result = self._run_item(config, item)
                result.items.append(item_result)
                if item_result.status == "failed" and not config.retry.continue_on_error:
                    raise RuntimeError(
                        f"Data sync job {config.name} failed at "
                        f"{item.symbol} {item.frequency.value}: {item_result.error}"
                    )
        finally:
            result.finished_at = result.finished_at or self.now()
            result.write(config.output_dir)
        return result

    def _items(self, config: DataSyncJobConfig) -> list[JobItem]:
        return [
            JobItem(
                symbol=symbol,
                frequency=frequency,
                adjust=config.adjust,
                start_date=config.start_date,
                end_date=config.end_date,
                source=config.catalog_source,
            )
            for symbol in config.symbols
            for frequency in config.frequencies
        ]

    def _run_item(self, config: DataSyncJobConfig, item: JobItem) -> JobItemResult:
        started_at = self.now()
        last_error: str | None = None
        for attempt in range(1, config.retry.max_attempts + 1):
            if config.retry.request_delay_seconds:
                self.sleep(config.retry.request_delay_seconds)
            try:
                self.service.sync(
                    symbols=[item.symbol],
                    start_date=item.start_date,
                    end_date=item.end_date,
                    frequency=item.frequency,
                    adjust=item.adjust,
                    source=item.source,
                )
                return JobItemResult(
                    job_name=config.name,
                    source=item.source,
                    exchange=config.exchange,
                    symbol=item.symbol,
                    frequency=item.frequency,
                    adjust=item.adjust,
                    start_date=item.start_date,
                    end_date=item.end_date,
                    status="success",
                    attempts=attempt,
                    rows=self._covered_rows(item),
                    started_at=started_at,
                    finished_at=self.now(),
                )
            except Exception as exc:
                last_error = str(exc)
                if attempt < config.retry.max_attempts and config.retry.failure_cooldown_seconds:
                    self.sleep(config.retry.failure_cooldown_seconds)

        return JobItemResult(
            job_name=config.name,
            source=item.source,
            exchange=config.exchange,
            symbol=item.symbol,
            frequency=item.frequency,
            adjust=item.adjust,
            start_date=item.start_date,
            end_date=item.end_date,
            status="failed",
            attempts=config.retry.max_attempts,
            rows=0,
            error=last_error,
            started_at=started_at,
            finished_at=self.now(),
        )

    def _covered_rows(self, item: JobItem) -> int:
        rows = 0
        for record in self.catalog.coverage(
            item.symbol,
            item.frequency,
            item.adjust,
            source=item.source,
        ):
            if record.end_date < item.start_date or record.start_date > item.end_date:
                continue
            rows += record.rows
        return rows
