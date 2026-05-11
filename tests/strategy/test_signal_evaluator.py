import pandas as pd
import pytest

from backtest.strategy.contracts import SignalState
from backtest.strategy.evaluation import SignalEvaluator


def test_signal_evaluator_reports_top_k_return_and_rank_ic():
    signals = pd.DataFrame(
        {
            "signal_time": [
                "2025-01-02 09:35:00",
                "2025-01-02 09:35:00",
                "2025-01-03 09:35:00",
                "2025-01-03 09:35:00",
            ],
            "instrument_id": ["BTC/USDT", "ETH/USDT", "BTC/USDT", "ETH/USDT"],
            "score": [0.9, 0.1, 0.2, 0.8],
            "rank": [1, 2, 2, 1],
            "signal_state": [SignalState.LONG_PREFERRED] * 4,
            "confidence": [0.9, 0.2, 0.4, 0.8],
            "horizon": ["5m"] * 4,
            "valid_until": [
                "2025-01-02 09:40:00",
                "2025-01-02 09:40:00",
                "2025-01-03 09:40:00",
                "2025-01-03 09:40:00",
            ],
            "reason": ["strong", "weak", "weak", "strong"],
        }
    )
    outcomes = pd.DataFrame(
        {
            "signal_time": [
                "2025-01-02 09:35:00",
                "2025-01-02 09:35:00",
                "2025-01-03 09:35:00",
                "2025-01-03 09:35:00",
            ],
            "instrument_id": ["BTC/USDT", "ETH/USDT", "BTC/USDT", "ETH/USDT"],
            "forward_return": [0.05, -0.01, -0.02, 0.04],
        }
    )

    result = SignalEvaluator(top_n=1).evaluate(signals, outcomes)

    assert result["signal_count"] == 4
    assert result["matched_count"] == 4
    assert result["top_n_mean_forward_return"] == pytest.approx(0.045)
    assert result["all_mean_forward_return"] == pytest.approx(0.015)
    assert result["rank_ic"] == pytest.approx(1.0)
