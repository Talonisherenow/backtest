from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class CashBalance(BaseModel):
    currency: str
    available: Decimal = Field(ge=Decimal("0"))
    frozen: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("currency must not be empty")
        return normalized


class PositionState(BaseModel):
    instrument_id: str
    quantity: Decimal = Field(ge=Decimal("0"))
    available_quantity: Decimal = Field(ge=Decimal("0"))
    avg_cost: Decimal = Field(ge=Decimal("0"))
    market_price: Decimal = Field(ge=Decimal("0"))
    currency: str

    @field_validator("instrument_id", "currency")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized


class PortfolioState(BaseModel):
    account_id: str = "default"
    cash: list[CashBalance] = Field(default_factory=list)
    positions: list[PositionState] = Field(default_factory=list)
    updated_at: datetime

    @field_validator("account_id")
    @classmethod
    def normalize_account_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("account_id must not be empty")
        return normalized

    @classmethod
    def empty(cls, updated_at: datetime, account_id: str = "default") -> "PortfolioState":
        return cls(account_id=account_id, cash=[], positions=[], updated_at=updated_at)

    def cash_by_currency(self) -> dict[str, CashBalance]:
        return {item.currency: item for item in self.cash}

    def position_by_instrument(self) -> dict[str, PositionState]:
        return {item.instrument_id: item for item in self.positions}

    def total_cash(self, currency: str) -> Decimal:
        item = self.cash_by_currency().get(currency.strip().upper())
        if item is None:
            return Decimal("0")
        return item.available + item.frozen
