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

    assert state.account_id == "default"
    assert state.cash == []
    assert state.positions == []
