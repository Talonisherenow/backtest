import pandas as pd

from backtest.portfolio.allocator import PortfolioAllocationConfig, PortfolioAllocator
from backtest.strategy.contracts import SignalState


def _signals() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "signal_time": ["2025-01-02 09:35:00"] * 3,
            "instrument_id": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
            "score": [0.9, 0.7, 0.1],
            "rank": [1, 2, 3],
            "signal_state": [SignalState.LONG_PREFERRED] * 3,
            "confidence": [0.9, 0.7, 0.1],
            "horizon": ["5m", "5m", "5m"],
            "valid_until": ["2025-01-02 09:40:00"] * 3,
            "reason": ["strong", "medium", "weak"],
        }
    )


def test_portfolio_allocator_builds_top_n_equal_weight_targets():
    allocator = PortfolioAllocator(
        PortfolioAllocationConfig(
            top_n=2,
            min_score=0.2,
            total_target_weight=0.6,
            max_weight_per_instrument=0.4,
            weighting="equal",
        )
    )

    targets = allocator.allocate(_signals())

    assert list(targets["instrument_id"]) == ["BTC/USDT", "ETH/USDT"]
    assert list(targets["target_weight"]) == [0.3, 0.3]


def test_portfolio_allocator_keeps_exit_preferred_as_zero_target():
    signals = pd.DataFrame(
        {
            "signal_time": ["2025-01-02 09:35:00"],
            "instrument_id": ["BTC/USDT"],
            "score": [0.0],
            "rank": [1],
            "signal_state": [SignalState.EXIT_PREFERRED],
            "confidence": [0.8],
            "horizon": ["5m"],
            "valid_until": ["2025-01-02 09:40:00"],
            "reason": ["exit_signal"],
        }
    )

    targets = PortfolioAllocator().allocate(signals)

    assert list(targets["instrument_id"]) == ["BTC/USDT"]
    assert list(targets["target_weight"]) == [0.0]
