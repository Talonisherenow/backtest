from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backtest.core.enums import AdjustMode, ExecutionTiming, Frequency
from backtest.core.symbols import normalize_symbol


class ProjectConfig(BaseModel):
    name: str


class StockPoolConfig(BaseModel):
    symbols: list[str]

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("stock_pool.symbols must not be empty")
        return [normalize_symbol(symbol) for symbol in value]


class DataConfig(BaseModel):
    source: str = "akshare"
    frequency: Frequency = Frequency.DAILY
    adjust: AdjustMode = AdjustMode.QFQ
    start_date: date
    end_date: date
    stock_pool: StockPoolConfig

    @model_validator(mode="after")
    def validate_dates(self) -> "DataConfig":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class SignalsConfig(BaseModel):
    type: Literal["file", "python"]
    path: Path
    function: str = "generate_signals"


class ExecutionConfig(BaseModel):
    timing: ExecutionTiming = ExecutionTiming.NEXT_OPEN
    initial_cash: float = Field(gt=0)
    commission_rate: float = Field(ge=0)
    min_commission: float = Field(ge=0)
    stamp_tax_rate: float = Field(ge=0)
    slippage_rate: float = Field(ge=0)
    board_lot_size: int = Field(default=100, gt=0)


class MetricsConfig(BaseModel):
    builtin: list[str] = Field(default_factory=list)
    custom: list[dict[str, str]] = Field(default_factory=list)


class ReportConfig(BaseModel):
    output_dir: Path = Path("runs")
    html: bool = True
    charts: bool = True


class BacktestConfig(BaseModel):
    project: ProjectConfig
    data: DataConfig
    signals: SignalsConfig
    execution: ExecutionConfig
    metrics: MetricsConfig
    report: ReportConfig
