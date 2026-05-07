# Universal Trading Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first phase of the universal trading architecture while preserving all existing A-share backtest behavior.

**Architecture:** Add market-neutral domain models for instruments, targets, orders, portfolio state, execution reports, and a simple SQLite order ledger. Introduce a reusable `OrderPlanner` beside the existing `BrokerEngine`, then protect current A-share backtest behavior with regression tests before any later internal migration.

**Tech Stack:** Python 3.11+, pandas, pydantic v2, pytest, existing Typer CLI and Parquet/report stack.

---

## Scope

This plan implements phase 1 only:

- Add universal domain models.
- Keep old A-share configs and tests working.
- Convert old `SignalFrame` data into `TargetPortfolioFrame`.
- Add an independent `OrderPlanner`.
- Add portfolio and execution report models.
- Add a simple SQLite `OrderLedger` for order intents and execution reports.
- Use a single default account in phase 1 while preserving an `account_id` field.
- Keep real broker/exchange API integration outside this phase.
- Treat `CCXT` as the first real API adapter for the next phase.
- Keep CLI as the default future live entrypoint and leave room for a daemon runner later.

The implementation must not touch unrelated generated files under `runs/`.

## File Structure

Create:

- `backtest/core/instruments.py`: market, exchange, asset class, instrument, and trading rule models.
- `backtest/core/targets.py`: `TargetPortfolioFrame` columns and validator.
- `backtest/core/orders.py`: `OrderIntent`, order enums, and execution report models.
- `backtest/execution/__init__.py`: public exports for execution infrastructure.
- `backtest/execution/ledger.py`: SQLite order ledger.
- `backtest/portfolio/__init__.py`: public exports for portfolio models.
- `backtest/portfolio/state.py`: `CashBalance`, `PositionState`, `PortfolioState`.
- `backtest/planning/__init__.py`: public exports for order planning.
- `backtest/planning/order_planner.py`: target-portfolio-to-order-intent planner.
- `tests/core/test_instruments.py`: tests for instruments and trading rules.
- `tests/core/test_targets.py`: tests for target portfolio validation.
- `tests/core/test_orders.py`: tests for order intent and execution report validation.
- `tests/execution/test_order_ledger.py`: tests for SQLite order ledger persistence.
- `tests/portfolio/test_state.py`: tests for portfolio state.
- `tests/planning/test_order_planner.py`: tests for order planning.

Modify:

- `backtest/core/enums.py`: add market-neutral enum values only if keeping them centralized fits local style.
- `backtest/core/__init__.py`: export new core models when useful.
- `backtest/signals/providers.py`: add a helper to convert legacy signals to target portfolio frames.
- `backtest/broker/engine.py`: keep unchanged in phase 1 unless a regression-only edit is needed.
- `tests/broker/test_execution.py`: add regression assertions only if the planner extraction changes observable behavior.
- `docs/data-contracts.md`: document `Instrument`, `TargetPortfolioFrame`, and `OrderIntent`.
- `docs/architecture.md`: add the universal trading architecture section.

## Task 1: Add Instrument And Trading Rule Models

**Files:**
- Create: `backtest/core/instruments.py`
- Test: `tests/core/test_instruments.py`

- [ ] **Step 1: Write failing instrument tests**

Create `tests/core/test_instruments.py`:

```python
from decimal import Decimal

import pytest

from backtest.core.instruments import (
    AssetClass,
    Instrument,
    Market,
    TradingRule,
)


def test_instrument_accepts_a_share_hk_stock_us_stock_and_crypto_ids():
    instruments = [
        Instrument(
            instrument_id="000001.SZ",
            market=Market.A_SHARE,
            exchange="SZSE",
            asset_class=AssetClass.STOCK,
            quote_currency="CNY",
        ),
        Instrument(
            instrument_id="00700.HK",
            market=Market.HK_STOCK,
            exchange="HKEX",
            asset_class=AssetClass.STOCK,
            quote_currency="HKD",
        ),
        Instrument(
            instrument_id="AAPL.US",
            market=Market.US_STOCK,
            exchange="NASDAQ",
            asset_class=AssetClass.STOCK,
            quote_currency="USD",
        ),
        Instrument(
            instrument_id="BTC-USDT.BINANCE",
            market=Market.CRYPTO_SPOT,
            exchange="BINANCE",
            asset_class=AssetClass.CRYPTO,
            quote_currency="USDT",
        ),
    ]

    assert [item.instrument_id for item in instruments] == [
        "000001.SZ",
        "00700.HK",
        "AAPL.US",
        "BTC-USDT.BINANCE",
    ]


def test_trading_rule_rounds_quantity_down_to_lot_size():
    rule = TradingRule(
        instrument_id="00700.HK",
        lot_size=Decimal("100"),
        tick_size=Decimal("0.01"),
        min_order_quantity=Decimal("100"),
        min_order_notional=Decimal("0"),
    )

    assert rule.round_quantity(Decimal("987")) == Decimal("900")
    assert rule.round_quantity(Decimal("99")) == Decimal("0")


def test_trading_rule_rejects_non_positive_lot_and_tick():
    with pytest.raises(ValueError, match="lot_size"):
        TradingRule(
            instrument_id="AAPL.US",
            lot_size=Decimal("0"),
            tick_size=Decimal("0.01"),
            min_order_quantity=Decimal("1"),
            min_order_notional=Decimal("0"),
        )

    with pytest.raises(ValueError, match="tick_size"):
        TradingRule(
            instrument_id="AAPL.US",
            lot_size=Decimal("1"),
            tick_size=Decimal("0"),
            min_order_quantity=Decimal("1"),
            min_order_notional=Decimal("0"),
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/core/test_instruments.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backtest.core.instruments'`.

- [ ] **Step 3: Implement instrument models**

Create `backtest/core/instruments.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/core/test_instruments.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/core/instruments.py tests/core/test_instruments.py
git commit -m "feat: add universal instrument models"
```

## Task 2: Add TargetPortfolioFrame Validation

**Files:**
- Create: `backtest/core/targets.py`
- Test: `tests/core/test_targets.py`

- [ ] **Step 1: Write failing target tests**

Create `tests/core/test_targets.py`:

```python
import pandas as pd
import pytest

from backtest.core.targets import TARGET_PORTFOLIO_COLUMNS, validate_target_portfolio_frame


def test_validate_target_portfolio_frame_normalizes_and_sorts():
    raw = pd.DataFrame(
        {
            "timestamp": ["2025-01-02", "2025-01-02"],
            "instrument_id": ["aapl.us", "00700.hk"],
            "target_weight": [0.3, 0.2],
        }
    )

    result = validate_target_portfolio_frame(raw)

    assert list(result.columns) == TARGET_PORTFOLIO_COLUMNS
    assert result["instrument_id"].tolist() == ["00700.HK", "AAPL.US"]
    assert result["target_weight"].tolist() == [0.2, 0.3]


def test_validate_target_portfolio_frame_rejects_daily_weight_sum_above_one():
    raw = pd.DataFrame(
        {
            "timestamp": ["2025-01-02", "2025-01-02"],
            "instrument_id": ["AAPL.US", "MSFT.US"],
            "target_weight": [0.7, 0.4],
        }
    )

    with pytest.raises(ValueError, match="target weight sum"):
        validate_target_portfolio_frame(raw)


def test_validate_target_portfolio_frame_rejects_duplicate_timestamp_instrument():
    raw = pd.DataFrame(
        {
            "timestamp": ["2025-01-02", "2025-01-02"],
            "instrument_id": ["AAPL.US", "AAPL.US"],
            "target_weight": [0.2, 0.3],
        }
    )

    with pytest.raises(ValueError, match="duplicate"):
        validate_target_portfolio_frame(raw)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/core/test_targets.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backtest.core.targets'`.

- [ ] **Step 3: Implement target validation**

Create `backtest/core/targets.py`:

```python
from collections.abc import Sequence

import pandas as pd

TARGET_PORTFOLIO_COLUMNS = ["timestamp", "instrument_id", "target_weight"]


def _normalize_instrument_id(value: object) -> str:
    normalized = str(value).strip().upper()
    if not normalized:
        raise ValueError("instrument_id must not be empty")
    return normalized


def validate_target_portfolio_frame(
    frame: pd.DataFrame,
    universe: Sequence[str] | None = None,
) -> pd.DataFrame:
    missing = set(TARGET_PORTFOLIO_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"TargetPortfolioFrame missing columns: {sorted(missing)}")

    result = frame.copy()
    result["timestamp"] = pd.to_datetime(result["timestamp"])
    result["instrument_id"] = result["instrument_id"].map(_normalize_instrument_id)
    result["target_weight"] = pd.to_numeric(result["target_weight"], errors="raise")

    required = ["timestamp", "instrument_id", "target_weight"]
    null_columns = [column for column in required if result[column].isna().any()]
    if null_columns:
        raise ValueError(f"TargetPortfolioFrame contains null required values: {null_columns}")

    if result.duplicated(["timestamp", "instrument_id"]).any():
        raise ValueError("TargetPortfolioFrame contains duplicate timestamp + instrument_id rows")

    if ((result["target_weight"] < 0) | (result["target_weight"] > 1)).any():
        raise ValueError("TargetPortfolioFrame target_weight must be between 0 and 1")

    daily_sum = result.groupby("timestamp")["target_weight"].sum()
    if (daily_sum > 1.0 + 1e-9).any():
        raise ValueError("TargetPortfolioFrame target weight sum exceeds 1.0 on at least one timestamp")

    if universe is not None:
        normalized_universe = {_normalize_instrument_id(item) for item in universe}
        outside = sorted(set(result["instrument_id"]) - normalized_universe)
        if outside:
            raise ValueError(f"TargetPortfolioFrame contains instruments outside universe: {outside}")

    return (
        result[TARGET_PORTFOLIO_COLUMNS]
        .sort_values(["timestamp", "instrument_id"])
        .reset_index(drop=True)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/core/test_targets.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/core/targets.py tests/core/test_targets.py
git commit -m "feat: add target portfolio frame contract"
```

## Task 3: Add Order Intent And Execution Report Models

**Files:**
- Create: `backtest/core/orders.py`
- Test: `tests/core/test_orders.py`

- [ ] **Step 1: Write failing order tests**

Create `tests/core/test_orders.py`:

```python
from datetime import datetime
from decimal import Decimal

import pytest

from backtest.core.orders import (
    ExecutionReport,
    ExecutionStatus,
    OrderIntent,
    OrderSide,
    OrderType,
    TimeInForce,
)


def test_order_intent_normalizes_ids_and_keeps_decimal_quantity():
    intent = OrderIntent(
        account_id="paper",
        client_order_id="co-1",
        strategy_id="mean-reversion",
        instrument_id="aapl.us",
        side=OrderSide.BUY,
        quantity=Decimal("1.25"),
        order_type=OrderType.LIMIT,
        limit_price=Decimal("180.12"),
        time_in_force=TimeInForce.DAY,
        created_at=datetime(2026, 5, 7, 9, 30),
        reason="rebalance",
    )

    assert intent.account_id == "paper"
    assert intent.instrument_id == "AAPL.US"
    assert intent.quantity == Decimal("1.25")
    assert intent.limit_price == Decimal("180.12")


def test_order_intent_rejects_limit_order_without_limit_price():
    with pytest.raises(ValueError, match="limit_price"):
        OrderIntent(
            account_id="default",
            client_order_id="co-1",
            strategy_id="s",
            instrument_id="AAPL.US",
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            created_at=datetime(2026, 5, 7, 9, 30),
        )


def test_execution_report_rejects_filled_quantity_above_order_quantity():
    with pytest.raises(ValueError, match="filled_quantity"):
        ExecutionReport(
            account_id="default",
            client_order_id="co-1",
            instrument_id="AAPL.US",
            status=ExecutionStatus.FILLED,
            order_quantity=Decimal("1"),
            filled_quantity=Decimal("2"),
            avg_fill_price=Decimal("180"),
            reported_at=datetime(2026, 5, 7, 9, 31),
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/core/test_orders.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backtest.core.orders'`.

- [ ] **Step 3: Implement order models**

Create `backtest/core/orders.py`:

```python
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

    @field_validator("account_id", "client_order_id", "strategy_id", "instrument_id")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        if "." in normalized or "-" in normalized:
            return normalized.upper()
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

    @field_validator("account_id", "client_order_id", "instrument_id")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        if "." in normalized or "-" in normalized:
            return normalized.upper()
        return normalized

    @model_validator(mode="after")
    def validate_fill(self) -> "ExecutionReport":
        if self.filled_quantity > self.order_quantity:
            raise ValueError("filled_quantity cannot exceed order_quantity")
        if self.filled_quantity > 0 and self.avg_fill_price is None:
            raise ValueError("avg_fill_price is required when filled_quantity is positive")
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/core/test_orders.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/core/orders.py tests/core/test_orders.py
git commit -m "feat: add order intent contracts"
```

## Task 4: Add Portfolio State Models

**Files:**
- Create: `backtest/portfolio/__init__.py`
- Create: `backtest/portfolio/state.py`
- Test: `tests/portfolio/test_state.py`

- [ ] **Step 1: Write failing portfolio tests**

Create `tests/portfolio/test_state.py`:

```python
from datetime import datetime
from decimal import Decimal

from backtest.portfolio.state import CashBalance, PortfolioState, PositionState


def test_portfolio_state_tracks_cash_by_currency_and_positions():
    state = PortfolioState(
        account_id="paper",
        cash=[
            CashBalance(currency="usd", available=Decimal("1000"), frozen=Decimal("25")),
            CashBalance(currency="hkd", available=Decimal("8000"), frozen=Decimal("0")),
        ],
        positions=[
            PositionState(
                instrument_id="aapl.us",
                quantity=Decimal("1.5"),
                available_quantity=Decimal("1.5"),
                avg_cost=Decimal("180"),
                market_price=Decimal("181"),
                currency="usd",
            )
        ],
        updated_at=datetime(2026, 5, 7, 9, 30),
    )

    assert state.account_id == "paper"
    assert state.cash_by_currency()["USD"].available == Decimal("1000")
    assert state.position_by_instrument()["AAPL.US"].quantity == Decimal("1.5")
    assert state.total_cash("USD") == Decimal("1025")


def test_empty_portfolio_has_no_positions_or_cash():
    state = PortfolioState.empty(updated_at=datetime(2026, 5, 7, 9, 30))

    assert state.cash == []
    assert state.positions == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/portfolio/test_state.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backtest.portfolio'`.

- [ ] **Step 3: Implement portfolio state**

Create `backtest/portfolio/state.py`:

```python
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
```

Create `backtest/portfolio/__init__.py`:

```python
from backtest.portfolio.state import CashBalance, PortfolioState, PositionState

__all__ = ["CashBalance", "PortfolioState", "PositionState"]
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/portfolio/test_state.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/portfolio tests/portfolio/test_state.py
git commit -m "feat: add portfolio state models"
```

## Task 5: Add Legacy Signal To TargetPortfolio Conversion

**Files:**
- Modify: `backtest/signals/providers.py`
- Test: `tests/signals/test_signal_providers.py`

- [ ] **Step 1: Add failing conversion test**

Append to `tests/signals/test_signal_providers.py`:

```python
def test_legacy_signal_frame_converts_to_target_portfolio_frame():
    raw = pd.DataFrame(
        {
            "date": ["2025-01-02"],
            "symbol": ["000001.SZ"],
            "target_weight": [0.2],
        }
    )

    result = legacy_signals_to_target_portfolio(raw, universe=["000001.SZ"])

    assert result.columns.tolist() == ["timestamp", "instrument_id", "target_weight"]
    assert str(result.loc[0, "timestamp"].date()) == "2025-01-02"
    assert result.loc[0, "instrument_id"] == "000001.SZ"
    assert result.loc[0, "target_weight"] == 0.2
```

At the top of the same test file, add:

```python
from backtest.signals.providers import legacy_signals_to_target_portfolio
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/signals/test_signal_providers.py::test_legacy_signal_frame_converts_to_target_portfolio_frame -v
```

Expected: FAIL with `ImportError` for `legacy_signals_to_target_portfolio`.

- [ ] **Step 3: Implement conversion helper**

Modify `backtest/signals/providers.py` by adding imports:

```python
from backtest.core.targets import validate_target_portfolio_frame
```

Add this function above `FileSignalProvider`:

```python
def legacy_signals_to_target_portfolio(
    signals: pd.DataFrame,
    universe: list[str] | None = None,
) -> pd.DataFrame:
    frame = signals.rename(
        columns={
            "date": "timestamp",
            "symbol": "instrument_id",
        }
    )
    return validate_target_portfolio_frame(frame, universe=universe)
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/signals/test_signal_providers.py::test_legacy_signal_frame_converts_to_target_portfolio_frame -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/signals/providers.py tests/signals/test_signal_providers.py
git commit -m "feat: convert legacy signals to target portfolios"
```

## Task 6: Add OrderPlanner

**Files:**
- Create: `backtest/planning/__init__.py`
- Create: `backtest/planning/order_planner.py`
- Test: `tests/planning/test_order_planner.py`

- [ ] **Step 1: Write failing planner tests**

Create `tests/planning/test_order_planner.py`:

```python
from datetime import datetime
from decimal import Decimal

import pandas as pd

from backtest.core.instruments import TradingRule
from backtest.core.orders import OrderSide, OrderType
from backtest.planning.order_planner import OrderPlanner
from backtest.portfolio.state import CashBalance, PortfolioState, PositionState


def test_order_planner_builds_buy_intent_from_target_weight():
    portfolio = PortfolioState(
        cash=[CashBalance(currency="CNY", available=Decimal("100000"))],
        positions=[],
        updated_at=datetime(2025, 1, 3, 9, 30),
    )
    targets = pd.DataFrame(
        {
            "timestamp": ["2025-01-02"],
            "instrument_id": ["000001.SZ"],
            "target_weight": [0.2],
        }
    )
    prices = {"000001.SZ": Decimal("10")}
    rules = {
        "000001.SZ": TradingRule(
            instrument_id="000001.SZ",
            lot_size=Decimal("100"),
            tick_size=Decimal("0.01"),
            min_order_quantity=Decimal("100"),
            min_order_notional=Decimal("0"),
            quantity_precision=0,
            price_precision=2,
        )
    }

    intents = OrderPlanner(strategy_id="demo").plan(
        targets=targets,
        portfolio=portfolio,
        prices=prices,
        rules=rules,
        created_at=datetime(2025, 1, 3, 9, 30),
    )

    assert len(intents) == 1
    assert intents[0].side == OrderSide.BUY
    assert intents[0].quantity == Decimal("2000")
    assert intents[0].order_type == OrderType.MARKET


def test_order_planner_builds_sell_intent_from_lower_target_weight():
    portfolio = PortfolioState(
        cash=[CashBalance(currency="CNY", available=Decimal("50000"))],
        positions=[
            PositionState(
                instrument_id="000001.SZ",
                quantity=Decimal("5000"),
                available_quantity=Decimal("5000"),
                avg_cost=Decimal("10"),
                market_price=Decimal("10"),
                currency="CNY",
            )
        ],
        updated_at=datetime(2025, 1, 3, 9, 30),
    )
    targets = pd.DataFrame(
        {
            "timestamp": ["2025-01-02"],
            "instrument_id": ["000001.SZ"],
            "target_weight": [0.2],
        }
    )
    prices = {"000001.SZ": Decimal("10")}
    rules = {
        "000001.SZ": TradingRule(
            instrument_id="000001.SZ",
            lot_size=Decimal("100"),
            tick_size=Decimal("0.01"),
            min_order_quantity=Decimal("100"),
            min_order_notional=Decimal("0"),
            quantity_precision=0,
            price_precision=2,
        )
    }

    intents = OrderPlanner(strategy_id="demo").plan(
        targets=targets,
        portfolio=portfolio,
        prices=prices,
        rules=rules,
        created_at=datetime(2025, 1, 3, 9, 30),
    )

    assert len(intents) == 1
    assert intents[0].side == OrderSide.SELL
    assert intents[0].quantity == Decimal("3000")


def test_order_planner_skips_below_lot_size_delta():
    portfolio = PortfolioState(
        cash=[CashBalance(currency="CNY", available=Decimal("100000"))],
        positions=[],
        updated_at=datetime(2025, 1, 3, 9, 30),
    )
    targets = pd.DataFrame(
        {
            "timestamp": ["2025-01-02"],
            "instrument_id": ["000001.SZ"],
            "target_weight": [0.001],
        }
    )
    prices = {"000001.SZ": Decimal("10")}
    rules = {
        "000001.SZ": TradingRule(
            instrument_id="000001.SZ",
            lot_size=Decimal("100"),
            tick_size=Decimal("0.01"),
            min_order_quantity=Decimal("100"),
            min_order_notional=Decimal("0"),
            quantity_precision=0,
            price_precision=2,
        )
    }

    intents = OrderPlanner(strategy_id="demo").plan(
        targets=targets,
        portfolio=portfolio,
        prices=prices,
        rules=rules,
        created_at=datetime(2025, 1, 3, 9, 30),
    )

    assert intents == []
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/planning/test_order_planner.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backtest.planning'`.

- [ ] **Step 3: Implement planner**

Create `backtest/planning/order_planner.py`:

```python
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pandas as pd

from backtest.core.instruments import TradingRule
from backtest.core.orders import OrderIntent, OrderSide, OrderType, TimeInForce
from backtest.core.targets import validate_target_portfolio_frame
from backtest.portfolio.state import PortfolioState


class OrderPlanner:
    def __init__(self, strategy_id: str) -> None:
        self.strategy_id = strategy_id

    def plan(
        self,
        targets: pd.DataFrame,
        portfolio: PortfolioState,
        prices: dict[str, Decimal],
        rules: dict[str, TradingRule],
        created_at: datetime,
    ) -> list[OrderIntent]:
        validated = validate_target_portfolio_frame(targets)
        total_equity = self._total_equity(portfolio, prices)
        positions = portfolio.position_by_instrument()
        intents: list[OrderIntent] = []

        for target in validated.itertuples(index=False):
            instrument_id = str(target.instrument_id).upper()
            price = prices.get(instrument_id)
            rule = rules.get(instrument_id)
            if price is None or rule is None or price <= 0:
                continue

            current_position = positions.get(instrument_id)
            current_quantity = current_position.quantity if current_position is not None else Decimal("0")
            current_value = current_quantity * price
            target_value = total_equity * Decimal(str(target.target_weight))
            delta_value = target_value - current_value
            if delta_value == 0:
                continue

            side = OrderSide.BUY if delta_value > 0 else OrderSide.SELL
            raw_quantity = abs(delta_value) / price
            quantity = rule.round_quantity(raw_quantity)
            if quantity <= 0:
                continue

            intents.append(
                OrderIntent(
                    client_order_id=f"{self.strategy_id}-{uuid4().hex}",
                    strategy_id=self.strategy_id,
                    instrument_id=instrument_id,
                    side=side,
                    quantity=quantity,
                    order_type=OrderType.MARKET,
                    time_in_force=TimeInForce.DAY,
                    created_at=created_at,
                    reason="target_weight_rebalance",
                )
            )

        return intents

    def _total_equity(self, portfolio: PortfolioState, prices: dict[str, Decimal]) -> Decimal:
        total = Decimal("0")
        for cash in portfolio.cash:
            total += cash.available + cash.frozen
        for position in portfolio.positions:
            price = prices.get(position.instrument_id, position.market_price)
            total += position.quantity * price
        return total
```

Create `backtest/planning/__init__.py`:

```python
from backtest.planning.order_planner import OrderPlanner

__all__ = ["OrderPlanner"]
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/planning/test_order_planner.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/planning tests/planning/test_order_planner.py
git commit -m "feat: add target portfolio order planner"
```

## Task 7: Add SQLite Order Ledger

**Files:**
- Create: `backtest/execution/__init__.py`
- Create: `backtest/execution/ledger.py`
- Test: `tests/execution/test_order_ledger.py`

- [ ] **Step 1: Write failing ledger test**

Create `tests/execution/test_order_ledger.py`:

```python
from datetime import datetime
from decimal import Decimal

from backtest.core.orders import (
    ExecutionReport,
    ExecutionStatus,
    OrderIntent,
    OrderSide,
    OrderType,
    TimeInForce,
)
from backtest.execution.ledger import SQLiteOrderLedger


def test_sqlite_order_ledger_records_intent_and_execution_report(tmp_path):
    ledger = SQLiteOrderLedger(tmp_path / "orders.sqlite")
    intent = OrderIntent(
        account_id="paper",
        client_order_id="co-1",
        strategy_id="demo",
        instrument_id="BTC-USDT.BINANCE",
        side=OrderSide.BUY,
        quantity=Decimal("0.25"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        created_at=datetime(2026, 5, 7, 9, 30),
        reason="rebalance",
    )
    report = ExecutionReport(
        account_id="paper",
        client_order_id="co-1",
        instrument_id="BTC-USDT.BINANCE",
        status=ExecutionStatus.FILLED,
        order_quantity=Decimal("0.25"),
        filled_quantity=Decimal("0.25"),
        avg_fill_price=Decimal("60000"),
        reported_at=datetime(2026, 5, 7, 9, 31),
        broker_order_id="broker-1",
        raw_response={"source": "sim"},
    )

    ledger.record_intent(intent)
    ledger.record_report(report)

    row = ledger.get_order(account_id="paper", client_order_id="co-1")
    assert row is not None
    assert row["account_id"] == "paper"
    assert row["instrument_id"] == "BTC-USDT.BINANCE"
    assert row["status"] == "filled"
    assert row["quantity"] == Decimal("0.25")
    assert row["filled_quantity"] == Decimal("0.25")
    assert row["avg_fill_price"] == Decimal("60000")
    assert row["broker_order_id"] == "broker-1"
    assert row["raw_response"] == {"source": "sim"}


def test_sqlite_order_ledger_lists_orders_by_account(tmp_path):
    ledger = SQLiteOrderLedger(tmp_path / "orders.sqlite")
    for account_id in ["paper", "live"]:
        ledger.record_intent(
            OrderIntent(
                account_id=account_id,
                client_order_id=f"{account_id}-1",
                strategy_id="demo",
                instrument_id="AAPL.US",
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.DAY,
                created_at=datetime(2026, 5, 7, 9, 30),
            )
        )

    assert [row["client_order_id"] for row in ledger.list_orders(account_id="paper")] == ["paper-1"]
    assert [row["client_order_id"] for row in ledger.list_orders(account_id="live")] == ["live-1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/execution/test_order_ledger.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backtest.execution'`.

- [ ] **Step 3: Implement SQLite order ledger**

Create `backtest/execution/ledger.py`:

```python
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from typing import Any

from backtest.core.orders import ExecutionReport, OrderIntent


class SQLiteOrderLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def record_intent(self, intent: OrderIntent) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO orders
                (
                    account_id, client_order_id, strategy_id, instrument_id, side,
                    quantity, order_type, limit_price, time_in_force, status,
                    created_at, reason, broker_order_id, filled_quantity,
                    avg_fill_price, reported_at, error, raw_response
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.account_id,
                    intent.client_order_id,
                    intent.strategy_id,
                    intent.instrument_id,
                    intent.side.value,
                    str(intent.quantity),
                    intent.order_type.value,
                    str(intent.limit_price) if intent.limit_price is not None else None,
                    intent.time_in_force.value,
                    "created",
                    intent.created_at.isoformat(),
                    intent.reason,
                    None,
                    "0",
                    None,
                    None,
                    "",
                    "{}",
                ),
            )

    def record_report(self, report: ExecutionReport) -> None:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE orders
                SET status = ?,
                    broker_order_id = ?,
                    filled_quantity = ?,
                    avg_fill_price = ?,
                    reported_at = ?,
                    error = ?,
                    raw_response = ?
                WHERE account_id = ? AND client_order_id = ?
                """,
                (
                    report.status.value,
                    report.broker_order_id,
                    str(report.filled_quantity),
                    str(report.avg_fill_price) if report.avg_fill_price is not None else None,
                    report.reported_at.isoformat(),
                    report.error,
                    json.dumps(report.raw_response, sort_keys=True),
                    report.account_id,
                    report.client_order_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Order intent not found: {report.account_id}/{report.client_order_id}")

    def get_order(self, account_id: str, client_order_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM orders
                WHERE account_id = ? AND client_order_id = ?
                """,
                (account_id, client_order_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_orders(self, account_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM orders
                WHERE account_id = ?
                ORDER BY created_at, client_order_id
                """,
                (account_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    account_id TEXT NOT NULL,
                    client_order_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    instrument_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    limit_price TEXT,
                    time_in_force TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    broker_order_id TEXT,
                    filled_quantity TEXT NOT NULL,
                    avg_fill_price TEXT,
                    reported_at TEXT,
                    error TEXT NOT NULL,
                    raw_response TEXT NOT NULL,
                    PRIMARY KEY (account_id, client_order_id)
                )
                """
            )

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "account_id": row["account_id"],
            "client_order_id": row["client_order_id"],
            "strategy_id": row["strategy_id"],
            "instrument_id": row["instrument_id"],
            "side": row["side"],
            "quantity": Decimal(row["quantity"]),
            "order_type": row["order_type"],
            "limit_price": Decimal(row["limit_price"]) if row["limit_price"] is not None else None,
            "time_in_force": row["time_in_force"],
            "status": row["status"],
            "created_at": datetime.fromisoformat(row["created_at"]),
            "reason": row["reason"],
            "broker_order_id": row["broker_order_id"],
            "filled_quantity": Decimal(row["filled_quantity"]),
            "avg_fill_price": Decimal(row["avg_fill_price"]) if row["avg_fill_price"] is not None else None,
            "reported_at": datetime.fromisoformat(row["reported_at"]) if row["reported_at"] is not None else None,
            "error": row["error"],
            "raw_response": json.loads(row["raw_response"]),
        }
```

Create `backtest/execution/__init__.py`:

```python
from backtest.execution.ledger import SQLiteOrderLedger

__all__ = ["SQLiteOrderLedger"]
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/execution/test_order_ledger.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/execution tests/execution/test_order_ledger.py
git commit -m "feat: add sqlite order ledger"
```

## Task 8: Verify Existing Backtest Behavior Remains Stable

**Files:**
- Test: `tests/broker/test_execution.py`
- Test: `tests/test_engine_e2e.py`

- [ ] **Step 1: Run existing broker and engine tests**

Run:

```bash
pytest tests/broker/test_execution.py tests/test_engine_e2e.py -v
```

Expected: PASS.

- [ ] **Step 2: Confirm phase-1 leaves `BrokerEngine` behavior unchanged**

Read `backtest/broker/engine.py` and confirm these public outputs are still produced by the existing path:

```python
BrokerResult(
    equity_curve=pd.DataFrame(equity_curve, columns=EQUITY_CURVE_COLUMNS),
    positions=pd.DataFrame(positions, columns=POSITIONS_COLUMNS),
    orders=pd.DataFrame(orders, columns=ORDERS_COLUMNS),
    trades=pd.DataFrame(trades, columns=TRADES_COLUMNS),
)
```

Keep these rejection strings unchanged because tests and reports rely on them:

```text
missing execution bar
below board lot
suspended
limit up
limit down
cash insufficient
T+1 available shares are zero
```

Do not edit `backtest/broker/engine.py` in this phase. The new `OrderPlanner` is validated independently in Task 6.

- [ ] **Step 3: Run regression tests after adding new modules**

Run:

```bash
pytest tests/broker/test_execution.py tests/test_engine_e2e.py -v
```

Expected: PASS.

- [ ] **Step 4: Run full test suite**

Run:

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 5: Record verification in the task notes**

No commit is needed for this task if no files changed. The verification result should be included in the final implementation summary.

## Task 9: Document New Contracts

**Files:**
- Modify: `docs/data-contracts.md`
- Modify: `docs/architecture.md`

- [ ] **Step 1: Update data contract documentation**

Add these sections to `docs/data-contracts.md` after the existing `SignalFrame` section:

````markdown
## Instrument

`Instrument` is the market-neutral identifier for a tradable or researchable
asset. It replaces assumptions that every asset is an A-share stock.

Required fields:

```text
instrument_id
market
exchange
asset_class
quote_currency
```

Examples:

```text
000001.SZ
00700.HK
AAPL.US
BTC-USDT.BINANCE
```

## TargetPortfolioFrame

Required columns:

```text
timestamp
instrument_id
target_weight
```

This frame expresses desired portfolio exposure. It is not an order and does
not imply that a broker accepted or filled anything.

## OrderIntent

`OrderIntent` is the internal order command created by a strategy or
`OrderPlanner`.

Required fields:

```text
client_order_id
strategy_id
instrument_id
side
quantity
order_type
time_in_force
created_at
```

`OrderIntent` is not an execution result. The system updates portfolio state
from `ExecutionReport`, not from the intent.

## OrderLedger

`OrderLedger` records order intent and execution report state. The phase-1
implementation stores rows in SQLite and scopes them by `account_id`.
````

- [ ] **Step 2: Update architecture documentation**

Add this section to `docs/architecture.md` before `Current MVP Limitations`:

````markdown
## Universal Trading Evolution

The next architecture separates strategy decisions from execution facts:

```text
MarketDataProvider
  -> StrategyRunner
  -> TargetPortfolio / OrderIntent
  -> RiskGate
  -> OrderLedger
  -> ExecutionAdapter
  -> ExecutionReport
  -> PortfolioState
```

Backtests and live trading should share strategy, target, order intent, risk,
and portfolio contracts. They should not share execution implementation:
backtests use a simulation adapter, while live trading uses broker or exchange
API adapters.
````

- [ ] **Step 3: Run documentation grep checks**

Run:

```bash
rg "TargetPortfolioFrame|OrderIntent|OrderLedger|Universal Trading Evolution" docs
```

Expected: output includes `docs/data-contracts.md` and `docs/architecture.md`.

- [ ] **Step 4: Commit**

```bash
git add docs/data-contracts.md docs/architecture.md
git commit -m "docs: describe universal trading contracts"
```

## Task 10: Final Verification

**Files:**
- No new files.

- [ ] **Step 1: Run full test suite**

Run:

```bash
pytest -q
```

Expected: PASS.

- [ ] **Step 2: Inspect git status**

Run:

```bash
git status --short
```

Expected: only pre-existing untracked chart artifacts remain, or a clean tree if the user removed them:

```text
?? runs/charts/000002_SZ_kline_300d.html
?? runs/charts/000002_SZ_kline_300d.svg
```

- [ ] **Step 3: Summarize implementation**

Report:

```text
Implemented phase-1 universal trading architecture foundations.
Existing A-share backtest behavior remains covered by the original test suite.
No real broker or exchange API adapter was added in this phase.
```

## Self-Review

Spec coverage:

- Instrument and trading rules: Task 1.
- Target portfolio: Task 2 and Task 5.
- Order intent and execution report: Task 3.
- Portfolio state: Task 4.
- Order planning: Task 6.
- SQLite order ledger: Task 7.
- Preserve existing A-share behavior: Task 8.
- Documentation: Task 9.
- Verification: Task 10.

Placeholder scan:

- The plan contains no placeholder markers and no unspecified implementation steps.
- Real API adapters are explicitly outside phase 1.

Type consistency:

- `instrument_id` is the neutral identifier across instruments, targets, orders, positions, and reports.
- `account_id` scopes orders and portfolio state while phase 1 defaults to one account.
- `Decimal` is used for quantities, prices, and cash in new trading models.
- Legacy `symbol` and `target_weight` remain supported through the conversion helper.
