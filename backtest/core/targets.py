from collections.abc import Sequence

import pandas as pd

TARGET_PORTFOLIO_COLUMNS = ["timestamp", "instrument_id", "target_weight"]


def _normalize_instrument_id(value: object) -> str:
    normalized = str(value).strip().upper()
    if not normalized:
        raise ValueError("instrument_id must not be empty")
    return normalized


def validate_target_portfolio_frame(
    frame: pd.DataFrame,
    universe: Sequence[str] | None = None,
) -> pd.DataFrame:
    missing = set(TARGET_PORTFOLIO_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"TargetPortfolioFrame missing columns: {sorted(missing)}")

    result = frame.copy()
    result["timestamp"] = pd.to_datetime(result["timestamp"])
    result["instrument_id"] = result["instrument_id"].map(_normalize_instrument_id)
    result["target_weight"] = pd.to_numeric(result["target_weight"], errors="raise")

    required = ["timestamp", "instrument_id", "target_weight"]
    null_columns = [column for column in required if result[column].isna().any()]
    if null_columns:
        raise ValueError(f"TargetPortfolioFrame contains null required values: {null_columns}")

    if result.duplicated(["timestamp", "instrument_id"]).any():
        raise ValueError("TargetPortfolioFrame contains duplicate timestamp + instrument_id rows")

    if ((result["target_weight"] < 0) | (result["target_weight"] > 1)).any():
        raise ValueError("TargetPortfolioFrame target_weight must be between 0 and 1")

    daily_sum = result.groupby("timestamp")["target_weight"].sum()
    if (daily_sum > 1.0 + 1e-9).any():
        raise ValueError("TargetPortfolioFrame target weight sum exceeds 1.0 on at least one timestamp")

    if universe is not None:
        normalized_universe = {_normalize_instrument_id(item) for item in universe}
        outside = sorted(set(result["instrument_id"]) - normalized_universe)
        if outside:
            raise ValueError(f"TargetPortfolioFrame contains instruments outside universe: {outside}")

    return (
        result[TARGET_PORTFOLIO_COLUMNS]
        .sort_values(["timestamp", "instrument_id"])
        .reset_index(drop=True)
    )
