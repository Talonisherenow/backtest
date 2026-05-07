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
