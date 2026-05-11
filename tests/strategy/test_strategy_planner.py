from pathlib import Path

import pandas as pd

from backtest.portfolio.allocator import PortfolioAllocationConfig, PortfolioAllocator
from backtest.signals.context import StrategyContext
from backtest.strategy.contracts import SignalState, StrategyPlan, validate_signal_score_frame
from backtest.strategy.planner import DefaultStrategyPlanner, LegacyStrategyPlanner


class DemoSignalGenerator:
    name = "demo-generator"

    def generate(self, context: StrategyContext) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "signal_time": ["2025-01-02 09:35:00", "2025-01-02 09:35:00"],
                "instrument_id": ["BTC/USDT", "ETH/USDT"],
                "score": [0.9, 0.5],
                "rank": [1, 2],
                "signal_state": [SignalState.LONG_PREFERRED, SignalState.LONG_PREFERRED],
                "confidence": [0.9, 0.5],
                "horizon": ["5m", "5m"],
                "valid_until": ["2025-01-02 09:40:00", "2025-01-02 09:40:00"],
                "reason": ["strong", "medium"],
            }
        )


def _context() -> StrategyContext:
    return StrategyContext(
        bars=pd.DataFrame(),
        stock_pool=["000001.SZ", "000002.SZ"],
        start_date="2025-01-02",
        end_date="2025-01-03",
        params={},
    )


def test_default_strategy_planner_builds_strategy_plan_from_generator_and_allocator():
    allocator = PortfolioAllocator(
        PortfolioAllocationConfig(top_n=1, total_target_weight=0.4, weighting="equal")
    )

    result = DefaultStrategyPlanner(
        generator=DemoSignalGenerator(),
        allocator=allocator,
        metadata={"case": "unit"},
    ).plan(_context())

    assert isinstance(result, StrategyPlan)
    pd.testing.assert_frame_equal(result.signals, validate_signal_score_frame(DemoSignalGenerator().generate(_context())))
    assert list(result.targets["instrument_id"]) == ["BTC/USDT"]
    assert list(result.targets["target_weight"]) == [0.4]
    assert result.metadata["case"] == "unit"
    assert result.metadata["generator"] == "demo-generator"
    assert result.metadata["allocator"] == "PortfolioAllocator"


def test_legacy_strategy_planner_wraps_python_signal_provider(tmp_path: Path):
    strategy_path = tmp_path / "strategy.py"
    strategy_path.write_text(
        """
import pandas as pd


def generate_signals(context):
    return pd.DataFrame(
        {
            "date": ["2025-01-02", "2025-01-02", "2025-01-03"],
            "symbol": ["000001.SZ", "000002.SZ", "000001.SZ"],
            "target_weight": [0.3, 0.1, 0.0],
        }
    )
""",
        encoding="utf-8",
    )

    result = LegacyStrategyPlanner.from_python(strategy_path, "generate_signals").plan(_context())

    assert isinstance(result, StrategyPlan)
    assert list(result.targets["target_weight"]) == [0.3, 0.1, 0.0]
    assert list(result.signals["rank"]) == [1, 2, 1]
    assert list(result.signals["signal_state"]) == [
        SignalState.LONG_PREFERRED.value,
        SignalState.LONG_PREFERRED.value,
        SignalState.EXIT_PREFERRED.value,
    ]
    assert result.metadata["planner"] == "legacy"


def test_strategy_package_exports_planner_classes():
    from backtest.strategy import DefaultStrategyPlanner as ExportedDefaultPlanner
    from backtest.strategy import LegacyStrategyPlanner as ExportedLegacyPlanner
    from backtest.strategy import StrategyPlanner as ExportedStrategyPlanner

    assert ExportedDefaultPlanner is DefaultStrategyPlanner
    assert ExportedLegacyPlanner is LegacyStrategyPlanner
    assert issubclass(ExportedDefaultPlanner, ExportedStrategyPlanner)
