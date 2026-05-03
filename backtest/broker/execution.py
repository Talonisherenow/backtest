from dataclasses import dataclass

import pandas as pd


@dataclass
class BrokerResult:
    equity_curve: pd.DataFrame
    positions: pd.DataFrame
    orders: pd.DataFrame
    trades: pd.DataFrame
