from typing import Any

import pandas as pd

from backtest.strategy.contracts import validate_signal_score_frame

OUTCOME_COLUMNS = ["signal_time", "instrument_id", "forward_return"]


class SignalEvaluator:
    def __init__(self, top_n: int = 5) -> None:
        if top_n < 1:
            raise ValueError("top_n must be at least 1")
        self.top_n = top_n

    def evaluate(self, signals: pd.DataFrame, outcomes: pd.DataFrame) -> dict[str, float | int]:
        validated_signals = validate_signal_score_frame(signals)
        validated_outcomes = self._validate_outcomes(outcomes)
        joined = validated_signals.merge(
            validated_outcomes,
            on=["signal_time", "instrument_id"],
            how="inner",
        )

        top_rows = (
            joined.sort_values(["signal_time", "rank", "instrument_id"])
            .groupby("signal_time", group_keys=False)
            .head(self.top_n)
        )
        bottom_rows = (
            joined.sort_values(["signal_time", "rank", "instrument_id"], ascending=[True, False, True])
            .groupby("signal_time", group_keys=False)
            .head(self.top_n)
        )

        return {
            "signal_count": len(validated_signals),
            "matched_count": len(joined),
            "all_mean_forward_return": self._mean(joined["forward_return"]),
            "top_n_mean_forward_return": self._mean(top_rows["forward_return"]),
            "top_bottom_spread": self._mean(top_rows["forward_return"]) - self._mean(bottom_rows["forward_return"]),
            "rank_ic": self._rank_ic(joined),
        }

    def _validate_outcomes(self, outcomes: pd.DataFrame) -> pd.DataFrame:
        missing = set(OUTCOME_COLUMNS) - set(outcomes.columns)
        if missing:
            raise ValueError(f"FutureOutcomeFrame missing columns: {sorted(missing)}")

        result = outcomes.copy()
        result["signal_time"] = pd.to_datetime(result["signal_time"])
        result["instrument_id"] = result["instrument_id"].map(self._normalize_instrument_id)
        result["forward_return"] = pd.to_numeric(result["forward_return"], errors="raise")
        null_columns = [column for column in OUTCOME_COLUMNS if result[column].isna().any()]
        if null_columns:
            raise ValueError(f"FutureOutcomeFrame contains null required values: {null_columns}")
        if result.duplicated(["signal_time", "instrument_id"]).any():
            raise ValueError("FutureOutcomeFrame contains duplicate signal_time + instrument_id rows")
        return result[OUTCOME_COLUMNS]

    def _rank_ic(self, joined: pd.DataFrame) -> float:
        correlations: list[float] = []
        for _, group in joined.groupby("signal_time", sort=True):
            if len(group) < 2:
                continue
            correlation = group["score"].rank().corr(group["forward_return"].rank())
            if pd.notna(correlation):
                correlations.append(float(correlation))
        if not correlations:
            return 0.0
        return float(pd.Series(correlations).mean())

    def _mean(self, series: pd.Series) -> float:
        if series.empty:
            return 0.0
        return float(series.mean())

    def _normalize_instrument_id(self, value: Any) -> str:
        normalized = str(value).strip().upper()
        if not normalized:
            raise ValueError("instrument_id must not be empty")
        return normalized
