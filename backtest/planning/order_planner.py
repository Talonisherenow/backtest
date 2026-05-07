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
                    account_id=portfolio.account_id,
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
