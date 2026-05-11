import pandas as pd
import pytest

from backtest.core.targets import TARGET_PORTFOLIO_COLUMNS
from backtest.runtime import BacktestRunner, LegacyBrokerExecutionBackend, NativeSimulationBackend
from backtest.signals.context import StrategyContext
from backtest.strategy.contracts import SIGNAL_SCORE_COLUMNS, StrategyPlan
from backtest.strategy.planner import StrategyPlanner
from tests.runtime.helpers import bars, execution_config


class StaticPlanner(StrategyPlanner):
    def plan(self, context: StrategyContext) -> StrategyPlan:
        signal_time = pd.Timestamp("2025-01-02")
        signals = pd.DataFrame(
            {
                "signal_time": [signal_time],
                "instrument_id": ["000001.SZ"],
                "score": [1.0],
                "rank": [1],
                "signal_state": ["long_preferred"],
                "confidence": [1.0],
                "horizon": ["1d"],
                "valid_until": [signal_time],
                "reason": ["static"],
            }
        )
        targets = pd.DataFrame(
            {
                "timestamp": [signal_time],
                "instrument_id": ["000001.SZ"],
                "target_weight": [0.2],
            }
        )
        return StrategyPlan(
            plan_time=signal_time.to_pydatetime(),
            signals=signals,
            targets=targets,
            metadata={"planner": "static"},
        )


@pytest.mark.parametrize("backend_factory", [LegacyBrokerExecutionBackend, NativeSimulationBackend])
def test_backtest_runner_collects_plans_and_executes_backend(backend_factory):
    runner = BacktestRunner(
        planner=StaticPlanner(),
        backend=backend_factory(),
        execution_config=execution_config(),
        planning_mode="batch",
    )

    result = runner.run(
        bars=bars(
            dates=["2025-01-02", "2025-01-03", "2025-01-06"],
            opens=[10.0, 10.0, 11.0],
            closes=[10.0, 11.0, 12.0],
        ),
        stock_pool=["000001.SZ"],
        start_date="2025-01-02",
        end_date="2025-01-06",
    )

    assert len(result.plans) == 1
    assert len(result.signals) == 1
    assert len(result.targets) == 1
    assert len(result.execution.trades) == 1
    assert result.metadata["backend"] == backend_factory.name


class CurrentDatePlanner(StrategyPlanner):
    def __init__(self) -> None:
        self.end_dates: list[str] = []

    def plan(self, context: StrategyContext) -> StrategyPlan:
        decision_time = pd.Timestamp(context.bars["date"].max())
        self.end_dates.append(context.end_date)
        if decision_time != pd.Timestamp("2025-01-02"):
            return StrategyPlan(
                plan_time=decision_time.to_pydatetime(),
                signals=pd.DataFrame(columns=SIGNAL_SCORE_COLUMNS),
                targets=pd.DataFrame(columns=TARGET_PORTFOLIO_COLUMNS),
                metadata={"planner": "current_date"},
            )
        signals = pd.DataFrame(
            {
                "signal_time": [decision_time],
                "instrument_id": ["000001.SZ"],
                "score": [1.0],
                "rank": [1],
                "signal_state": ["long_preferred"],
                "confidence": [1.0],
                "horizon": ["1d"],
                "valid_until": [decision_time],
                "reason": ["current_date"],
            }
        )
        targets = pd.DataFrame(
            {
                "timestamp": [decision_time],
                "instrument_id": ["000001.SZ"],
                "target_weight": [0.2],
            }
        )
        return StrategyPlan(
            plan_time=decision_time.to_pydatetime(),
            signals=signals,
            targets=targets,
            metadata={"planner": "current_date"},
        )


def test_backtest_runner_walk_forward_calls_planner_per_decision_date_and_collects_current_rows():
    planner = CurrentDatePlanner()
    runner = BacktestRunner(
        planner=planner,
        backend=NativeSimulationBackend(),
        execution_config=execution_config(),
        planning_mode="walk_forward",
    )

    result = runner.run(
        bars=bars(
            dates=["2025-01-02", "2025-01-03", "2025-01-06"],
            opens=[10.0, 10.0, 11.0],
            closes=[10.0, 11.0, 12.0],
        ),
        stock_pool=["000001.SZ"],
        start_date="2025-01-02",
        end_date="2025-01-06",
    )

    assert planner.end_dates == ["2025-01-02", "2025-01-03", "2025-01-06"]
    assert len(result.plans) == 1
    assert result.targets["timestamp"].tolist() == [pd.Timestamp("2025-01-02")]
    assert len(result.execution.trades) == 1
