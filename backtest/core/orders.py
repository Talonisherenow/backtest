from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(StrEnum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"


class ExecutionStatus(StrEnum):
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    FAILED = "failed"


class OrderIntent(BaseModel):
    account_id: str = "default"
    client_order_id: str
    strategy_id: str
    instrument_id: str
    side: OrderSide
    quantity: Decimal = Field(gt=Decimal("0"))
    order_type: OrderType
    limit_price: Decimal | None = Field(default=None, gt=Decimal("0"))
    time_in_force: TimeInForce = TimeInForce.DAY
    created_at: datetime
    reason: str = ""

    @field_validator("account_id", "client_order_id", "strategy_id")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("instrument_id")
    @classmethod
    def normalize_instrument_id(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("instrument_id must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_order_type_fields(self) -> "OrderIntent":
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders")
        if self.order_type == OrderType.MARKET and self.limit_price is not None:
            raise ValueError("limit_price must be omitted for market orders")
        return self


class ExecutionReport(BaseModel):
    account_id: str = "default"
    client_order_id: str
    instrument_id: str
    status: ExecutionStatus
    order_quantity: Decimal = Field(gt=Decimal("0"))
    filled_quantity: Decimal = Field(ge=Decimal("0"))
    avg_fill_price: Decimal | None = Field(default=None, ge=Decimal("0"))
    reported_at: datetime
    broker_order_id: str | None = None
    error: str = ""
    raw_response: dict[str, Any] = Field(default_factory=dict)

    @field_validator("account_id", "client_order_id")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized

    @field_validator("instrument_id")
    @classmethod
    def normalize_instrument_id(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("instrument_id must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_fill(self) -> "ExecutionReport":
        if self.filled_quantity > self.order_quantity:
            raise ValueError("filled_quantity cannot exceed order_quantity")
        if self.filled_quantity > 0 and self.avg_fill_price is None:
            raise ValueError("avg_fill_price is required when filled_quantity is positive")
        return self
