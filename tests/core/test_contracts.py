from datetime import date

from backtest.core.contracts import OrderRecord


def test_order_record_preserves_transfer_fee():
    order = OrderRecord(
        date=date(2025, 1, 3),
        symbol="000001.SZ",
        side="buy",
        requested_shares=1000,
        filled_shares=1000,
        price=10.0,
        commission=5.0,
        tax=0.0,
        transfer_fee=0.1,
        slippage_cost=0.0,
        status="filled",
    )

    assert order.transfer_fee == 0.1


def test_order_record_defaults_transfer_fee_to_zero():
    order = OrderRecord(
        date=date(2025, 1, 3),
        symbol="000001.SZ",
        side="buy",
        requested_shares=1000,
        filled_shares=1000,
        price=10.0,
        status="filled",
    )

    assert order.transfer_fee == 0.0
