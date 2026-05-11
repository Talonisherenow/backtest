from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backtest.core.targets import validate_target_portfolio_frame
from backtest.strategy.contracts import StrategyPlan, validate_signal_score_frame


@dataclass(frozen=True)
class BacktestExecutionResult:
    equity_curve: pd.DataFrame
    positions: pd.DataFrame
    orders: pd.DataFrame
    trades: pd.DataFrame
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "equity_curve", self.equity_curve.copy())
        object.__setattr__(self, "positions", self.positions.copy())
        object.__setattr__(self, "orders", self.orders.copy())
        object.__setattr__(self, "trades", self.trades.copy())
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class BacktestRunResult:
    plans: list[StrategyPlan]
    signals: pd.DataFrame
    targets: pd.DataFrame
    execution: BacktestExecutionResult
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "plans", list(self.plans))
        object.__setattr__(self, "signals", validate_signal_score_frame(self.signals))
        object.__setattr__(self, "targets", validate_target_portfolio_frame(self.targets))
        object.__setattr__(self, "metadata", dict(self.metadata))
