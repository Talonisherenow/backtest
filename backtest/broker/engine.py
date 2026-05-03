import pandas as pd

from backtest.broker.account import Account
from backtest.broker.costs import AShareCostModel
from backtest.broker.execution import BrokerResult
from backtest.broker.slippage import FixedRateSlippageModel
from backtest.config.models import ExecutionConfig
from backtest.core.enums import ExecutionTiming


class BrokerEngine:
    def __init__(self, config: ExecutionConfig) -> None:
        self.config = config
        self.cost_model = AShareCostModel(
            config.commission_rate,
            config.min_commission,
            config.stamp_tax_rate,
            config.transfer_fee_rate,
        )
        self.slippage_model = FixedRateSlippageModel(config.slippage_rate)

    def run(self, bars: pd.DataFrame, signals: pd.DataFrame) -> BrokerResult:
        if self.config.timing != ExecutionTiming.NEXT_OPEN:
            raise NotImplementedError("BrokerEngine MVP supports only next_open execution")

        account = Account(cash=self.config.initial_cash)
        bars = bars.sort_values(["date", "symbol"]).reset_index(drop=True)
        signals = signals.sort_values(["date", "symbol"]).reset_index(drop=True)
        dates = sorted(bars["date"].drop_duplicates())
        orders: list[dict] = []
        trades: list[dict] = []
        positions: list[dict] = []
        equity_curve: list[dict] = []
        scheduled_signals: dict[pd.Timestamp, list[pd.DataFrame]] = {}

        for signal_date, daily_signals in signals.groupby("date", sort=True):
            execution_date = self._next_date(dates, signal_date)
            if execution_date is None:
                continue
            scheduled_signals.setdefault(execution_date, []).append(daily_signals)

        first_execution_date = min(scheduled_signals) if scheduled_signals else None

        for trade_date in dates:
            day_bars = bars[bars["date"] == trade_date].set_index("symbol")

            for daily_signals in scheduled_signals.get(trade_date, []):
                equity_before = self._mark_to_market(account, day_bars)

                for signal in daily_signals.itertuples(index=False):
                    symbol = signal.symbol
                    if symbol not in day_bars.index:
                        orders.append(self._rejected(trade_date, symbol, "buy", 0, "missing execution bar"))
                        continue
                    bar = day_bars.loc[symbol]
                    current_value = account.shares(symbol) * float(bar["open"])
                    target_value = equity_before * float(signal.target_weight)
                    delta_value = target_value - current_value
                    if abs(delta_value) < 1e-9:
                        continue
                    side = "buy" if delta_value > 0 else "sell"
                    price = self.slippage_model.apply(side, float(bar["open"]))
                    requested_shares = int(abs(delta_value) / price)
                    requested_shares = (requested_shares // self.config.board_lot_size) * self.config.board_lot_size
                    if requested_shares <= 0:
                        orders.append(self._rejected(trade_date, symbol, side, 0, "below board lot"))
                        continue
                    rejection_reason = self._constraint_rejection(side, bar)
                    if rejection_reason:
                        orders.append(self._rejected(trade_date, symbol, side, requested_shares, rejection_reason))
                        continue
                    if side == "buy":
                        filled = self._buy(account, trade_date, symbol, requested_shares, price, orders, trades)
                    else:
                        filled = self._sell(account, trade_date, symbol, requested_shares, price, orders, trades)
                    if filled:
                        positions.append({"date": trade_date, "symbol": symbol, "shares": account.shares(symbol)})

            if first_execution_date is not None and trade_date >= first_execution_date:
                equity_curve.append(
                    {
                        "date": trade_date,
                        "equity": self._mark_to_market(account, day_bars),
                        "cash": account.cash,
                    }
                )

        return BrokerResult(
            equity_curve=pd.DataFrame(equity_curve),
            positions=pd.DataFrame(positions),
            orders=pd.DataFrame(orders),
            trades=pd.DataFrame(trades),
        )

    def _next_date(self, dates: list[pd.Timestamp], signal_date: pd.Timestamp) -> pd.Timestamp | None:
        for date_value in dates:
            if date_value > signal_date:
                return date_value
        return None

    def _mark_to_market(self, account: Account, day_bars: pd.DataFrame) -> float:
        value = account.cash
        for symbol, shares in account.positions.items():
            if symbol in day_bars.index:
                value += shares * float(day_bars.loc[symbol, "close"])
        return value

    def _constraint_rejection(self, side: str, bar: pd.Series) -> str:
        is_suspended = bar.get("is_suspended", False)
        if pd.notna(is_suspended) and bool(is_suspended):
            return "suspended"
        if side == "buy" and pd.notna(bar.get("limit_up")) and float(bar["open"]) >= float(bar["limit_up"]):
            return "limit up"
        if side == "sell" and pd.notna(bar.get("limit_down")) and float(bar["open"]) <= float(bar["limit_down"]):
            return "limit down"
        return ""

    def _buy(
        self,
        account: Account,
        trade_date,
        symbol: str,
        shares: int,
        price: float,
        orders: list[dict],
        trades: list[dict],
    ) -> bool:
        value = shares * price
        cost = self.cost_model.calculate("buy", value)
        affordable = int((account.cash - cost.total) / price)
        affordable = (affordable // self.config.board_lot_size) * self.config.board_lot_size
        filled_shares = min(shares, affordable)
        if filled_shares <= 0:
            orders.append(self._rejected(trade_date, symbol, "buy", shares, "cash insufficient"))
            return False
        value = filled_shares * price
        cost = self.cost_model.calculate("buy", value)
        account.cash -= value + cost.total
        account.add_position(symbol, filled_shares, available_date=trade_date + pd.Timedelta(days=1))
        orders.append(
            self._filled(
                trade_date,
                symbol,
                "buy",
                shares,
                filled_shares,
                price,
                cost.commission,
                cost.tax,
                cost.transfer_fee,
            )
        )
        trades.append({"date": trade_date, "symbol": symbol, "side": "buy", "shares": filled_shares, "price": price})
        return True

    def _sell(
        self,
        account: Account,
        trade_date,
        symbol: str,
        shares: int,
        price: float,
        orders: list[dict],
        trades: list[dict],
    ) -> bool:
        available = account.available_shares(symbol, trade_date)
        if available <= 0:
            orders.append(self._rejected(trade_date, symbol, "sell", shares, "T+1 available shares are zero"))
            return False
        filled_shares = min(shares, available)
        value = filled_shares * price
        cost = self.cost_model.calculate("sell", value)
        account.cash += value - cost.total
        account.remove_available_shares(symbol, filled_shares, trade_date)
        orders.append(
            self._filled(
                trade_date,
                symbol,
                "sell",
                shares,
                filled_shares,
                price,
                cost.commission,
                cost.tax,
                cost.transfer_fee,
            )
        )
        trades.append({"date": trade_date, "symbol": symbol, "side": "sell", "shares": filled_shares, "price": price})
        return True

    def _filled(
        self,
        date,
        symbol: str,
        side: str,
        requested: int,
        filled: int,
        price: float,
        commission: float,
        tax: float,
        transfer_fee: float,
    ) -> dict:
        status = "filled" if requested == filled else "adjusted"
        return {
            "date": date,
            "symbol": symbol,
            "side": side,
            "requested_shares": requested,
            "filled_shares": filled,
            "price": price,
            "commission": commission,
            "tax": tax,
            "transfer_fee": transfer_fee,
            "slippage_cost": 0.0,
            "status": status,
            "reason": "",
        }

    def _rejected(self, date, symbol: str, side: str, requested: int, reason: str) -> dict:
        return {
            "date": date,
            "symbol": symbol,
            "side": side,
            "requested_shares": requested,
            "filled_shares": 0,
            "price": 0.0,
            "commission": 0.0,
            "tax": 0.0,
            "transfer_fee": 0.0,
            "slippage_cost": 0.0,
            "status": "rejected",
            "reason": reason,
        }
