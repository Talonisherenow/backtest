from decimal import Decimal, ROUND_DOWN
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class Market(StrEnum):
    A_SHARE = "a_share"
    HK_STOCK = "hk_stock"
    US_STOCK = "us_stock"
    CRYPTO_SPOT = "crypto_spot"


class AssetClass(StrEnum):
    STOCK = "stock"
    ETF = "etf"
    CRYPTO = "crypto"
    CASH = "cash"


class Instrument(BaseModel):
    instrument_id: str
    market: Market
    exchange: str
    asset_class: AssetClass
    quote_currency: str
    name: str | None = None

    @field_validator("instrument_id", "exchange", "quote_currency")
    @classmethod
    def normalize_upper_text(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized


class TradingRule(BaseModel):
    instrument_id: str
    lot_size: Decimal = Field(gt=Decimal("0"))
    tick_size: Decimal = Field(gt=Decimal("0"))
    min_order_quantity: Decimal = Field(ge=Decimal("0"))
    min_order_notional: Decimal = Field(ge=Decimal("0"))
    quantity_precision: int = Field(default=8, ge=0)
    price_precision: int = Field(default=8, ge=0)

    @field_validator("instrument_id")
    @classmethod
    def normalize_instrument_id(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("instrument_id must not be empty")
        return normalized

    def round_quantity(self, quantity: Decimal) -> Decimal:
        if quantity <= 0:
            return Decimal("0")
        units = (quantity / self.lot_size).to_integral_value(rounding=ROUND_DOWN)
        rounded = units * self.lot_size
        if rounded < self.min_order_quantity:
            return Decimal("0")
        quant = Decimal("1").scaleb(-self.quantity_precision)
        return rounded.quantize(quant, rounding=ROUND_DOWN)

    def round_price(self, price: Decimal) -> Decimal:
        if price <= 0:
            return Decimal("0")
        ticks = (price / self.tick_size).to_integral_value(rounding=ROUND_DOWN)
        rounded = ticks * self.tick_size
        quant = Decimal("1").scaleb(-self.price_precision)
        return rounded.quantize(quant, rounding=ROUND_DOWN)
