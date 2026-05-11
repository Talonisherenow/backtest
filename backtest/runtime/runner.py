from typing import Literal

import pandas as pd

from backtest.config.models import ExecutionConfig
from backtest.core.frames import validate_bar_frame
from backtest.core.targets import TARGET_PORTFOLIO_COLUMNS
from backtest.runtime.backend import ExecutionBackend
from backtest.runtime.results import BacktestRunResult
from backtest.signals.context import StrategyContext
from backtest.strategy.contracts import SIGNAL_SCORE_COLUMNS, StrategyPlan
from backtest.strategy.planner import StrategyPlanner

PlanningMode = Literal["batch", "walk_forward"]


class BacktestRunner:
    def __init__(
        self,
        planner: StrategyPlanner,
        backend: ExecutionBackend,
        execution_config: ExecutionConfig,
        planning_mode: PlanningMode = "walk_forward",
    ) -> None:
        if planning_mode not in ("batch", "walk_forward"):
            raise ValueError("planning_mode must be 'batch' or 'walk_forward'")
        self.planner = planner
        self.backend = backend
        self.execution_config = execution_config
        self.planning_mode = planning_mode

    def run(
        self,
        bars: pd.DataFrame,
        stock_pool: list[str],
        start_date: str,
        end_date: str,
    ) -> BacktestRunResult:
        validated_bars = validate_bar_frame(bars)
        plans = self._plan(validated_bars, stock_pool, start_date, end_date)
        signals = self._concat_frames([plan.signals for plan in plans], SIGNAL_SCORE_COLUMNS)
        targets = self._concat_frames([plan.targets for plan in plans], TARGET_PORTFOLIO_COLUMNS)
        execution = self.backend.execute(
            bars=validated_bars,
            targets=targets,
            config=self.execution_config,
        )
        return BacktestRunResult(
            plans=plans,
            signals=signals,
            targets=targets,
            execution=execution,
            metadata={
                "backend": self.backend.name,
                "planning_mode": self.planning_mode,
            },
        )

    def _plan(
        self,
        bars: pd.DataFrame,
        stock_pool: list[str],
        start_date: str,
        end_date: str,
    ) -> list[StrategyPlan]:
        if self.planning_mode == "batch":
            context = StrategyContext(
                bars=bars,
                stock_pool=stock_pool,
                start_date=start_date,
                end_date=end_date,
                params={},
            )
            return [self.planner.plan(context)]
        return self._walk_forward_plans(bars, stock_pool, start_date)

    def _walk_forward_plans(
        self,
        bars: pd.DataFrame,
        stock_pool: list[str],
        start_date: str,
    ) -> list[StrategyPlan]:
        plans: list[StrategyPlan] = []
        for decision_time in sorted(bars["date"].drop_duplicates()):
            decision_time = pd.Timestamp(decision_time)
            visible_bars = bars[bars["date"] <= decision_time]
            context = StrategyContext(
                bars=visible_bars,
                stock_pool=stock_pool,
                start_date=start_date,
                end_date=decision_time.date().isoformat(),
                params={},
            )
            plan = self.planner.plan(context)
            current_signals = plan.signals[plan.signals["signal_time"] == decision_time]
            current_targets = plan.targets[plan.targets["timestamp"] == decision_time]
            if current_signals.empty and current_targets.empty:
                continue
            plans.append(
                StrategyPlan(
                    plan_time=plan.plan_time,
                    signals=self._concat_frames([current_signals], SIGNAL_SCORE_COLUMNS),
                    targets=self._concat_frames([current_targets], TARGET_PORTFOLIO_COLUMNS),
                    metadata=plan.metadata,
                )
            )
        return plans

    def _concat_frames(self, frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
        non_empty = [frame for frame in frames if not frame.empty]
        if not non_empty:
            return pd.DataFrame(columns=columns)
        return pd.concat(non_empty, ignore_index=True)[columns]
