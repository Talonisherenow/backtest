from typing import Protocol

import pandas as pd

from backtest.broker.engine import BrokerEngine
from backtest.config.models import ExecutionConfig
from backtest.runtime.adapters import (
    broker_result_to_execution_result,
    target_portfolio_to_legacy_signal_frame,
)
from backtest.runtime.results import BacktestExecutionResult


class ExecutionBackend(Protocol):
    name: str

    def execute(
        self,
        bars: pd.DataFrame,
        targets: pd.DataFrame,
        config: ExecutionConfig,
    ) -> BacktestExecutionResult:
        ...


class LegacyBrokerExecutionBackend:
    name = "legacy_broker"

    def execute(
        self,
        bars: pd.DataFrame,
        targets: pd.DataFrame,
        config: ExecutionConfig,
    ) -> BacktestExecutionResult:
        signals = target_portfolio_to_legacy_signal_frame(targets)
        broker_result = BrokerEngine(config).run(bars, signals)
        return broker_result_to_execution_result(broker_result, backend_name=self.name)
