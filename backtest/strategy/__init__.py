from backtest.strategy.contracts import (
    SIGNAL_SCORE_COLUMNS,
    SignalState,
    StrategyPlan,
    validate_signal_score_frame,
)
from backtest.strategy.evaluation import SignalEvaluator
from backtest.strategy.generator import SignalGenerator

_PLANNER_EXPORTS = {
    "DefaultStrategyPlanner",
    "LegacyStrategyPlanner",
    "StrategyPlanner",
}

__all__ = [
    "DefaultStrategyPlanner",
    "LegacyStrategyPlanner",
    "SIGNAL_SCORE_COLUMNS",
    "SignalEvaluator",
    "SignalGenerator",
    "SignalState",
    "StrategyPlan",
    "StrategyPlanner",
    "validate_signal_score_frame",
]


def __getattr__(name: str):
    if name in _PLANNER_EXPORTS:
        from backtest.strategy import planner

        return getattr(planner, name)
    raise AttributeError(f"module 'backtest.strategy' has no attribute {name!r}")
