from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BacktestResultContext:
    equity_curve: Any
    positions: Any
    trades: Any
    orders: Any
    bars: Any
    config: Any
