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


def test_order_intent_normalizes_instrument_id_and_keeps_decimal_quantity():
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
    assert intent.client_order_id == "co-1"
    assert intent.strategy_id == "mean-reversion"
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
