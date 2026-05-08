from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from backtest.core.enums import AdjustMode, Frequency
from backtest.core.symbols import normalize_symbol


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
