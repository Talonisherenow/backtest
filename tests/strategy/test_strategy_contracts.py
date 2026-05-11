from datetime import datetime

import pandas as pd
import pytest

from backtest.strategy.contracts import (
    SIGNAL_SCORE_COLUMNS,
    SignalState,
    StrategyPlan,
    validate_signal_score_frame,
)


def _signal_score_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "signal_time": ["2025-01-02 09:35:00", "2025-01-02 09:35:00"],
            "instrument_id": ["btc/usdt", "eth/usdt"],
            "score": [0.82, 0.45],
            "rank": [1, 2],
            "signal_state": [SignalState.LONG_PREFERRED, "neutral"],
            "confidence": [0.72, 0.51],
            "horizon": ["5m", "5m"],
            "valid_until": ["2025-01-02 09:40:00", "2025-01-02 09:40:00"],
            "reason": ["volume_breakout", "weaker_momentum"],
        }
    )


def test_validate_signal_score_frame_normalizes_and_orders_columns():
    result = validate_signal_score_frame(_signal_score_frame())

    assert list(result.columns) == SIGNAL_SCORE_COLUMNS
    assert result.loc[0, "instrument_id"] == "BTC/USDT"
    assert result.loc[0, "signal_state"] == "long_preferred"
    assert result.loc[0, "signal_time"] == pd.Timestamp("2025-01-02 09:35:00")


def test_validate_signal_score_frame_rejects_invalid_confidence():
    frame = _signal_score_frame()
    frame.loc[0, "confidence"] = 1.5

    with pytest.raises(ValueError, match="confidence"):
        validate_signal_score_frame(frame)


def test_validate_signal_score_frame_rejects_duplicate_signal_rows():
    frame = pd.concat([_signal_score_frame(), _signal_score_frame().iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate"):
        validate_signal_score_frame(frame)


def test_strategy_plan_validates_signals_and_targets():
    targets = pd.DataFrame(
        {
            "timestamp": ["2025-01-02 09:35:00"],
            "instrument_id": ["btc/usdt"],
            "target_weight": [0.3],
        }
    )

    result = StrategyPlan(
        plan_time=datetime(2025, 1, 2, 9, 35),
        signals=_signal_score_frame(),
        targets=targets,
        metadata={"source": "unit-test"},
    )

    assert result.signals.loc[0, "instrument_id"] == "BTC/USDT"
    assert result.targets.loc[0, "instrument_id"] == "BTC/USDT"
    assert result.metadata == {"source": "unit-test"}
