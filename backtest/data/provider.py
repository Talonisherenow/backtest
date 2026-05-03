from typing import Protocol

import pandas as pd

from backtest.core.contracts import BarRequest


class DataProvider(Protocol):
    def fetch_bars(self, request: BarRequest) -> pd.DataFrame:
        raise NotImplementedError
