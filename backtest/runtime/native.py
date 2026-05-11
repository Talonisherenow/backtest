import pandas as pd

from backtest.broker.account import Account
from backtest.broker.costs import AShareCostModel
from backtest.broker.execution import (
    EQUITY_CURVE_COLUMNS,
    ORDERS_COLUMNS,
    POSITIONS_COLUMNS,
    TRADES_COLUMNS,
)
from backtest.broker.slippage import FixedRateSlippageModel
from backtest.config.models import ExecutionConfig
from backtest.core.enums import ExecutionTiming
from backtest.core.targets import validate_target_portfolio_frame
from backtest.runtime.results import BacktestExecutionResult


class NativeSimulationBackend:
    name = "native_simulation"

    def __init__(self) -> None:
        self.cost_model: AShareCostModel | None = None
        self.slippage_model: FixedRateSlippageModel | None = None
        self.config: ExecutionConfig | None = None

    def execute(
        self,
        bars: pd.DataFrame,
        targets: pd.DataFrame,
        config: ExecutionConfig,
    ) -> BacktestExecutionResult:
        if config.timing != ExecutionTiming.NEXT_OPEN:
            raise NotImplementedError("NativeSimulationBackend MVP supports only next_open execution")

        self.config = config
        self.cost_model = AShareCostModel(
            config.commission_rate,
            config.min_commission,
            config.stamp_tax_rate,
            config.transfer_fee_rate,
        )
        self.slippage_model = FixedRateSlippageModel(config.slippage_rate)

        account = Account(cash=config.initial_cash)
        bars = bars.sort_values(["date", "symbol"]).reset_index(drop=True)
        targets = validate_target_portfolio_frame(targets).assign(_sequence=range(len(targets)))
        targets = targets.sort_values(["timestamp", "_sequence"], kind="mergesort").reset_index(drop=True)
        dates = sorted(bars["date"].drop_duplicates())
        orders: list[dict] = []
        trades: list[dict] = []
        positions: list[dict] = []
        equity_curve: list[dict] = []
        last_close_by_symbol: dict[str, float] = {}
        scheduled_targets: dict[pd.Timestamp, list[pd.DataFrame]] = {}

        for target_date, daily_targets in targets.groupby("timestamp", sort=True):
            execution_date = self._next_date(dates, target_date)
            if execution_date is None:
                continue
            scheduled = daily_targets.assign(_target_date=target_date)
            scheduled_targets.setdefault(execution_date, []).append(scheduled)

        first_execution_date = min(scheduled_targets) if scheduled_targets else None

        for trade_date in dates:
            day_bars = bars[bars["date"] == trade_date].set_index("symbol")
            trade_date_targets = scheduled_targets.get(trade_date, [])
            if trade_date_targets:
                daily_targets = pd.concat(trade_date_targets, ignore_index=True)
                daily_targets = (
                    daily_targets.sort_values(["_target_date", "_sequence"], kind="mergesort")
                    .drop_duplicates(subset=["instrument_id"], keep="last")
                    .reset_index(drop=True)
                )
                intents = self._build_intents(account, day_bars, daily_targets, last_close_by_symbol)
                sell_intents = [item for item in intents if item["side"] == "sell"]
                buy_intents = [item for item in intents if item["side"] == "buy"]
                for intent in sell_intents + buy_intents:
                    if intent["reason"]:
                        orders.append(
                            self._rejected(
                                trade_date,
                                intent["symbol"],
                                intent["side"],
                                intent["requested_shares"],
                                intent["reason"],
                            )
                        )
                        continue
                    if intent["side"] == "buy":
                        filled = self._buy(
                            account,
                            trade_date,
                            intent["symbol"],
                            intent["requested_shares"],
                            intent["price"],
                            orders,
                            trades,
                        )
                    else:
                        filled = self._sell(
                            account,
                            trade_date,
                            intent["symbol"],
                            intent["requested_shares"],
                            intent["price"],
                            orders,
                            trades,
                        )
                    if filled:
                        positions.append(
                            {
                                "date": trade_date,
                                "symbol": intent["symbol"],
                                "shares": account.shares(intent["symbol"]),
                            }
                        )

            if first_execution_date is not None and trade_date >= first_execution_date:
                equity_curve.append(
                    {
                        "date": trade_date,
                        "equity": self._mark_to_market(account, day_bars, "close", last_close_by_symbol),
                        "cash": account.cash,
                    }
                )
            for symbol, bar in day_bars.iterrows():
                if pd.notna(bar.get("close")):
                    last_close_by_symbol[symbol] = float(bar["close"])

        return BacktestExecutionResult(
            equity_curve=pd.DataFrame(equity_curve, columns=EQUITY_CURVE_COLUMNS),
            positions=pd.DataFrame(positions, columns=POSITIONS_COLUMNS),
            orders=pd.DataFrame(orders, columns=ORDERS_COLUMNS),
            trades=pd.DataFrame(trades, columns=TRADES_COLUMNS),
            metadata={"backend": self.name},
        )

    def _next_date(self, dates: list[pd.Timestamp], target_date: pd.Timestamp) -> pd.Timestamp | None:
        for date_value in dates:
            if date_value > target_date:
                return date_value
        return None

    def _build_intents(
        self,
        account: Account,
        day_bars: pd.DataFrame,
        daily_targets: pd.DataFrame,
        last_close_by_symbol: dict[str, float],
    ) -> list[dict]:
        equity_before = self._mark_to_market(account, day_bars, "open", last_close_by_symbol)
        planned_values = {
            symbol: self._position_value(symbol, shares, day_bars, "open", last_close_by_symbol)
            for symbol, shares in account.positions.items()
        }
        intents: list[dict] = []

        for target in daily_targets.itertuples(index=False):
            symbol = target.instrument_id
            target_value = equity_before * float(target.target_weight)
            current_value = planned_values.get(symbol, 0.0)
            delta_value = target_value - current_value
            if abs(delta_value) < 1e-9:
                continue
            side = "buy" if delta_value > 0 else "sell"
            planned_values[symbol] = target_value

            if symbol not in day_bars.index:
                intents.append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "requested_shares": 0,
                        "price": 0.0,
                        "reason": "missing execution bar",
                    }
                )
                continue

            bar = day_bars.loc[symbol]
            assert self.config is not None
            assert self.slippage_model is not None
            price = self.slippage_model.apply(side, float(bar["open"]))
            requested_shares = int(abs(delta_value) / price)
            requested_shares = (requested_shares // self.config.board_lot_size) * self.config.board_lot_size
            reason = ""
            if requested_shares <= 0:
                reason = "below board lot"
            else:
                reason = self._constraint_rejection(side, bar, price)
            intents.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "requested_shares": requested_shares,
                    "price": price,
                    "reason": reason,
                }
            )

        return intents

    def _mark_to_market(
        self,
        account: Account,
        day_bars: pd.DataFrame,
        price_column: str,
        last_close_by_symbol: dict[str, float],
    ) -> float:
        value = account.cash
        for symbol, shares in account.positions.items():
            value += self._position_value(symbol, shares, day_bars, price_column, last_close_by_symbol)
        return value

    def _position_value(
        self,
        symbol: str,
        shares: int,
        day_bars: pd.DataFrame,
        price_column: str,
        last_close_by_symbol: dict[str, float],
    ) -> float:
        if symbol in day_bars.index and pd.notna(day_bars.loc[symbol].get(price_column)):
            return shares * float(day_bars.loc[symbol, price_column])
        if symbol in last_close_by_symbol:
            return shares * last_close_by_symbol[symbol]
        return 0.0

    def _constraint_rejection(self, side: str, bar: pd.Series, price: float) -> str:
        is_suspended = bar.get("is_suspended", False)
        if pd.notna(is_suspended) and bool(is_suspended):
            return "suspended"
        if side == "buy" and pd.notna(bar.get("limit_up")) and price >= float(bar["limit_up"]):
            return "limit up"
        if side == "sell" and pd.notna(bar.get("limit_down")) and price <= float(bar["limit_down"]):
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
        filled_shares = self._max_affordable_buy_shares(account.cash, shares, price)
        if filled_shares <= 0:
            orders.append(self._rejected(trade_date, symbol, "buy", shares, "cash insufficient"))
            return False
        assert self.cost_model is not None
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

    def _max_affordable_buy_shares(self, cash: float, requested_shares: int, price: float) -> int:
        assert self.config is not None
        assert self.cost_model is not None
        board_lot_size = self.config.board_lot_size
        max_by_price = int(cash / price)
        max_shares = min(requested_shares, (max_by_price // board_lot_size) * board_lot_size)
        low = 0
        high = max_shares // board_lot_size
        best = 0

        while low <= high:
            midpoint = (low + high) // 2
            candidate_shares = midpoint * board_lot_size
            value = candidate_shares * price
            cost = self.cost_model.calculate("buy", value)
            if value + cost.total <= cash + 1e-9:
                best = candidate_shares
                low = midpoint + 1
            else:
                high = midpoint - 1

        return best

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
        assert self.cost_model is not None
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
