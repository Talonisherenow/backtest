from collections.abc import Sequence

import pandas as pd

from backtest.core.enums import AdjustMode, Frequency
from backtest.core.symbols import normalize_symbol

BAR_COLUMNS = [
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "frequency",
    "adjust",
]
SIGNAL_COLUMNS = ["date", "symbol", "target_weight"]


def validate_bar_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = set(BAR_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"BarFrame missing columns: {sorted(missing)}")

    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"])
    result["symbol"] = result["symbol"].map(normalize_symbol)
    result["frequency"] = result["frequency"].map(lambda value: Frequency(value).value)
    result["adjust"] = result["adjust"].map(lambda value: AdjustMode(value).value)

    price_cols = ["open", "high", "low", "close"]
    for col in price_cols:
        result[col] = pd.to_numeric(result[col], errors="raise")
    result["volume"] = pd.to_numeric(result["volume"], errors="raise")
    result["amount"] = pd.to_numeric(result["amount"], errors="raise")

    if (result["high"] < result["low"]).any():
        raise ValueError("BarFrame contains high lower than low")
    if (result[price_cols] < 0).any().any():
        raise ValueError("BarFrame contains negative prices")

    return result.sort_values(["symbol", "date"]).reset_index(drop=True)


def validate_signal_frame(
    frame: pd.DataFrame, stock_pool: Sequence[str] | None = None
) -> pd.DataFrame:
    missing = set(SIGNAL_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"SignalFrame missing columns: {sorted(missing)}")

    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"])
    result["symbol"] = result["symbol"].map(normalize_symbol)
    result["target_weight"] = pd.to_numeric(result["target_weight"], errors="raise")

    if result.duplicated(["date", "symbol"]).any():
        raise ValueError("SignalFrame contains duplicate date + symbol rows")
    if ((result["target_weight"] < 0) | (result["target_weight"] > 1)).any():
        raise ValueError("SignalFrame target_weight must be between 0 and 1")

    daily_sum = result.groupby("date")["target_weight"].sum()
    if (daily_sum > 1.0 + 1e-9).any():
        raise ValueError("SignalFrame target weight sum exceeds 1.0 on at least one date")

    if stock_pool is not None:
        normalized_pool = {normalize_symbol(symbol) for symbol in stock_pool}
        outside = sorted(set(result["symbol"]) - normalized_pool)
        if outside:
            raise ValueError(f"SignalFrame contains symbols outside stock pool: {outside}")

    return result.sort_values(["date", "symbol"]).reset_index(drop=True)
