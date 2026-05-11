from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

import pandas as pd

from backtest.core.targets import validate_target_portfolio_frame

SIGNAL_SCORE_COLUMNS = [
    "signal_time",
    "instrument_id",
    "score",
    "rank",
    "signal_state",
    "confidence",
    "horizon",
    "valid_until",
    "reason",
]


class SignalState(StrEnum):
    LONG_PREFERRED = "long_preferred"
    NEUTRAL = "neutral"
    EXIT_PREFERRED = "exit_preferred"
    BLOCKED = "blocked"


def _normalize_instrument_id(value: object) -> str:
    normalized = str(value).strip().upper()
    if not normalized:
        raise ValueError("instrument_id must not be empty")
    return normalized


def _normalize_signal_state(value: object) -> str:
    if isinstance(value, SignalState):
        return value.value
    return SignalState(str(value).strip()).value


def validate_signal_score_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = set(SIGNAL_SCORE_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"SignalScoreFrame missing columns: {sorted(missing)}")

    result = frame.copy()
    result["signal_time"] = pd.to_datetime(result["signal_time"])
    result["valid_until"] = pd.to_datetime(result["valid_until"])
    result["instrument_id"] = result["instrument_id"].map(_normalize_instrument_id)
    result["score"] = pd.to_numeric(result["score"], errors="raise")
    result["rank"] = pd.to_numeric(result["rank"], errors="raise")
    result["confidence"] = pd.to_numeric(result["confidence"], errors="raise")
    result["signal_state"] = result["signal_state"].map(_normalize_signal_state)
    result["horizon"] = result["horizon"].map(lambda value: str(value).strip())
    result["reason"] = result["reason"].map(lambda value: str(value).strip())

    required = SIGNAL_SCORE_COLUMNS
    null_columns = [column for column in required if result[column].isna().any()]
    if null_columns:
        raise ValueError(f"SignalScoreFrame contains null required values: {null_columns}")

    if result.duplicated(["signal_time", "instrument_id"]).any():
        raise ValueError("SignalScoreFrame contains duplicate signal_time + instrument_id rows")

    if ((result["confidence"] < 0) | (result["confidence"] > 1)).any():
        raise ValueError("SignalScoreFrame confidence must be between 0 and 1")

    if (result["horizon"] == "").any():
        raise ValueError("SignalScoreFrame horizon must not be empty")

    return (
        result[SIGNAL_SCORE_COLUMNS]
        .sort_values(["signal_time", "rank", "instrument_id"])
        .reset_index(drop=True)
    )


@dataclass(frozen=True)
class StrategyPlan:
    plan_time: datetime
    signals: pd.DataFrame
    targets: pd.DataFrame
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "signals", validate_signal_score_frame(self.signals))
        object.__setattr__(self, "targets", validate_target_portfolio_frame(self.targets))
        object.__setattr__(self, "metadata", dict(self.metadata))
