import pandas as pd

from backtest.broker.execution import BrokerResult
from backtest.core.frames import validate_signal_frame
from backtest.core.targets import validate_target_portfolio_frame
from backtest.runtime.results import BacktestExecutionResult


def target_portfolio_to_legacy_signal_frame(targets: pd.DataFrame) -> pd.DataFrame:
    validated = validate_target_portfolio_frame(targets)
    result = validated.rename(
        columns={
            "timestamp": "date",
            "instrument_id": "symbol",
        }
    )
    return validate_signal_frame(result[["date", "symbol", "target_weight"]])


def broker_result_to_execution_result(
    broker_result: BrokerResult,
    backend_name: str,
) -> BacktestExecutionResult:
    return BacktestExecutionResult(
        equity_curve=broker_result.equity_curve,
        positions=broker_result.positions,
        orders=broker_result.orders,
        trades=broker_result.trades,
        metadata={"backend": backend_name},
    )
