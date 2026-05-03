from dataclasses import dataclass

import pandas as pd

EQUITY_CURVE_COLUMNS = ["date", "equity", "cash"]
POSITIONS_COLUMNS = ["date", "symbol", "shares"]
ORDERS_COLUMNS = [
    "date",
    "symbol",
    "side",
    "requested_shares",
    "filled_shares",
    "price",
    "commission",
    "tax",
    "transfer_fee",
    "slippage_cost",
    "status",
    "reason",
]
TRADES_COLUMNS = ["date", "symbol", "side", "shares", "price"]


@dataclass
class BrokerResult:
    equity_curve: pd.DataFrame
    positions: pd.DataFrame
    orders: pd.DataFrame
    trades: pd.DataFrame
