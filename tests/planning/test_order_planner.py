from datetime import datetime
from decimal import Decimal

import pandas as pd

from backtest.core.instruments import TradingRule
from backtest.core.orders import OrderSide, OrderType
from backtest.planning.order_planner import OrderPlanner
from backtest.portfolio.state import CashBalance, PortfolioState, PositionState


def _a_share_rule() -> TradingRule:
    return TradingRule(
        instrument_id="000001.SZ",
        lot_size=Decimal("100"),
        tick_size=Decimal("0.01"),
        min_order_quantity=Decimal("100"),
        min_order_notional=Decimal("0"),
        quantity_precision=0,
        price_precision=2,
    )


def test_order_planner_builds_buy_intent_from_target_weight():
    portfolio = PortfolioState(
        account_id="paper",
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
    rules = {"000001.SZ": _a_share_rule()}

    intents = OrderPlanner(strategy_id="demo").plan(
        targets=targets,
        portfolio=portfolio,
        prices=prices,
        rules=rules,
        created_at=datetime(2025, 1, 3, 9, 30),
    )

    assert len(intents) == 1
    assert intents[0].account_id == "paper"
    assert intents[0].side == OrderSide.BUY
    assert intents[0].quantity == Decimal("2000")
    assert intents[0].order_type == OrderType.MARKET


def test_order_planner_builds_sell_intent_from_lower_target_weight():
    portfolio = PortfolioState(
        account_id="paper",
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
    rules = {"000001.SZ": _a_share_rule()}

    intents = OrderPlanner(strategy_id="demo").plan(
        targets=targets,
        portfolio=portfolio,
        prices=prices,
        rules=rules,
        created_at=datetime(2025, 1, 3, 9, 30),
    )

    assert len(intents) == 1
    assert intents[0].account_id == "paper"
    assert intents[0].side == OrderSide.SELL
    assert intents[0].quantity == Decimal("3000")


def test_order_planner_skips_below_lot_size_delta():
    portfolio = PortfolioState(
        account_id="paper",
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
    rules = {"000001.SZ": _a_share_rule()}

    intents = OrderPlanner(strategy_id="demo").plan(
        targets=targets,
        portfolio=portfolio,
        prices=prices,
        rules=rules,
        created_at=datetime(2025, 1, 3, 9, 30),
    )

    assert intents == []
