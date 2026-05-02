from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from backtest.core.enums import (
    AdjustMode,
    Frequency,
    MetricResultKind,
    OrderSide,
    OrderStatus,
)


class BarRequest(BaseModel):
    symbols: list[str]
    start_date: date
    end_date: date
    frequency: Frequency = Frequency.DAILY
    adjust: AdjustMode = AdjustMode.QFQ
    source: str = "akshare"


class CatalogRecord(BaseModel):
    symbol: str
    frequency: Frequency
    adjust: AdjustMode
    start_date: date
    end_date: date
    rows: int
    source: str
    cache_path: Path
    updated_at: datetime
    quality_status: str = "ok"


class CrawlTaskRecord(BaseModel):
    task_id: int | None = None
    symbol: str
    frequency: Frequency
    adjust: AdjustMode
    start_date: date
    end_date: date
    source: str
    status: str = "pending"
    attempts: int = 0
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class OrderRecord(BaseModel):
    date: date
    symbol: str
    side: OrderSide
    requested_shares: int
    filled_shares: int
    price: float
    commission: float = 0.0
    tax: float = 0.0
    slippage_cost: float = 0.0
    status: OrderStatus
    reason: str = ""


class MetricResult(BaseModel):
    name: str
    kind: MetricResultKind
    value: Any
