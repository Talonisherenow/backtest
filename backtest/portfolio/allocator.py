from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from backtest.core.targets import TARGET_PORTFOLIO_COLUMNS, validate_target_portfolio_frame
from backtest.strategy.contracts import SignalState, validate_signal_score_frame


class PortfolioAllocationConfig(BaseModel):
    top_n: int | None = Field(default=None, gt=0)
    min_score: float | None = None
    total_target_weight: float = Field(default=1.0, ge=0, le=1)
    max_weight_per_instrument: float = Field(default=1.0, ge=0, le=1)
    weighting: Literal["equal", "score"] = "equal"


class PortfolioAllocator:
    def __init__(self, config: PortfolioAllocationConfig | None = None) -> None:
        self.config = config or PortfolioAllocationConfig()

    def allocate(self, signals: pd.DataFrame) -> pd.DataFrame:
        validated = validate_signal_score_frame(signals)
        rows: list[dict[str, object]] = []

        for signal_time, group in validated.groupby("signal_time", sort=True):
            exit_rows = group[group["signal_state"] == SignalState.EXIT_PREFERRED.value]
            for signal in exit_rows.itertuples(index=False):
                rows.append(
                    {
                        "timestamp": signal_time,
                        "instrument_id": signal.instrument_id,
                        "target_weight": 0.0,
                    }
                )

            candidates = group[group["signal_state"] == SignalState.LONG_PREFERRED.value].copy()
            if self.config.min_score is not None:
                candidates = candidates[candidates["score"] >= self.config.min_score]
            candidates = candidates.sort_values(["rank", "score", "instrument_id"], ascending=[True, False, True])
            if self.config.top_n is not None:
                candidates = candidates.head(self.config.top_n)
            if candidates.empty:
                continue

            weights = self._weights(candidates)
            for signal, weight in zip(candidates.itertuples(index=False), weights, strict=True):
                rows.append(
                    {
                        "timestamp": signal_time,
                        "instrument_id": signal.instrument_id,
                        "target_weight": weight,
                    }
                )

        frame = pd.DataFrame(rows, columns=TARGET_PORTFOLIO_COLUMNS)
        return validate_target_portfolio_frame(frame)

    def _weights(self, signals: pd.DataFrame) -> list[float]:
        if self.config.weighting == "equal":
            raw_weights = [self.config.total_target_weight / len(signals)] * len(signals)
        else:
            positive_scores = signals["score"].clip(lower=0)
            score_sum = float(positive_scores.sum())
            if score_sum <= 0:
                raw_weights = [self.config.total_target_weight / len(signals)] * len(signals)
            else:
                raw_weights = [
                    self.config.total_target_weight * float(score) / score_sum
                    for score in positive_scores
                ]

        return [
            min(weight, self.config.max_weight_per_instrument)
            for weight in raw_weights
        ]
