from typing import Protocol

import pandas as pd

from backtest.signals.context import StrategyContext


class SignalGenerator(Protocol):
    def generate(self, context: StrategyContext) -> pd.DataFrame:
        ...
