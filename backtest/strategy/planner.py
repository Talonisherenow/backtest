from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.portfolio.allocator import PortfolioAllocator
from backtest.signals.context import StrategyContext
from backtest.signals.providers import (
    FileSignalProvider,
    PythonSignalProvider,
    legacy_signals_to_target_portfolio,
)
from backtest.strategy.contracts import (
    SignalState,
    StrategyPlan,
    validate_signal_score_frame,
)
from backtest.strategy.generator import SignalGenerator


class StrategyPlanner:
    def plan(self, context: StrategyContext) -> StrategyPlan:
        raise NotImplementedError


class DefaultStrategyPlanner(StrategyPlanner):
    def __init__(
        self,
        generator: SignalGenerator,
        allocator: PortfolioAllocator,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.generator = generator
        self.allocator = allocator
        self.metadata = dict(metadata or {})

    def plan(self, context: StrategyContext) -> StrategyPlan:
        signals = validate_signal_score_frame(self.generator.generate(context))
        targets = self.allocator.allocate(signals)
        metadata = {
            **self.metadata,
            "generator": getattr(self.generator, "name", self.generator.__class__.__name__),
            "allocator": self.allocator.__class__.__name__,
        }
        return StrategyPlan(
            plan_time=self._plan_time(signals),
            signals=signals,
            targets=targets,
            metadata=metadata,
        )

    def _plan_time(self, signals: pd.DataFrame) -> datetime:
        if signals.empty:
            return datetime.now()
        return pd.Timestamp(signals["signal_time"].max()).to_pydatetime()


class LegacyStrategyPlanner(StrategyPlanner):
    def __init__(
        self,
        provider: FileSignalProvider | PythonSignalProvider,
        source_type: str,
    ) -> None:
        self.provider = provider
        self.source_type = source_type

    @classmethod
    def from_python(
        cls,
        path: str | Path,
        function_name: str = "generate_signals",
    ) -> "LegacyStrategyPlanner":
        return cls(PythonSignalProvider(path, function_name=function_name), source_type="python")

    @classmethod
    def from_file(cls, path: str | Path) -> "LegacyStrategyPlanner":
        return cls(FileSignalProvider(path), source_type="file")

    def plan(self, context: StrategyContext) -> StrategyPlan:
        if isinstance(self.provider, PythonSignalProvider):
            legacy_signals = self.provider.load(context=context)
        else:
            legacy_signals = self.provider.load(stock_pool=context.stock_pool)

        targets = legacy_signals_to_target_portfolio(legacy_signals, universe=context.stock_pool)
        signals = self._signals_from_targets(targets)
        return StrategyPlan(
            plan_time=self._plan_time(signals),
            signals=signals,
            targets=targets,
            metadata={"planner": "legacy", "source_type": self.source_type},
        )

    def _signals_from_targets(self, targets: pd.DataFrame) -> pd.DataFrame:
        if targets.empty:
            return validate_signal_score_frame(
                pd.DataFrame(
                    columns=[
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
                )
            )

        result = targets.rename(columns={"timestamp": "signal_time"}).copy()
        result["score"] = result["target_weight"]
        result["rank"] = result.groupby("signal_time")["score"].rank(
            method="first",
            ascending=False,
        )
        result["signal_state"] = result["target_weight"].map(
            lambda value: SignalState.LONG_PREFERRED.value
            if float(value) > 0
            else SignalState.EXIT_PREFERRED.value
        )
        result["confidence"] = result["target_weight"].clip(lower=0, upper=1)
        result["horizon"] = "legacy_signal"
        result["valid_until"] = result["signal_time"]
        result["reason"] = "legacy_target_weight"
        return validate_signal_score_frame(
            result[
                [
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
            ]
        )

    def _plan_time(self, signals: pd.DataFrame) -> datetime:
        if signals.empty:
            return datetime.now()
        return pd.Timestamp(signals["signal_time"].max()).to_pydatetime()
