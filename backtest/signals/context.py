from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class StrategyContext:
    bars: pd.DataFrame
    stock_pool: list[str]
    start_date: str
    end_date: str
    params: dict[str, Any]
