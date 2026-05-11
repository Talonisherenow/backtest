import pandas as pd

from backtest.broker.execution import BrokerResult
from backtest.runtime.adapters import (
    broker_result_to_execution_result,
    target_portfolio_to_legacy_signal_frame,
)


def test_target_portfolio_frame_converts_to_legacy_signal_frame():
    targets = pd.DataFrame(
        {
            "timestamp": ["2025-01-02"],
            "instrument_id": ["000001.SZ"],
            "target_weight": [0.2],
        }
    )

    result = target_portfolio_to_legacy_signal_frame(targets)

    assert list(result.columns) == ["date", "symbol", "target_weight"]
    assert result.iloc[0].to_dict() == {
        "date": pd.Timestamp("2025-01-02"),
        "symbol": "000001.SZ",
        "target_weight": 0.2,
    }


def test_broker_result_converts_to_backtest_execution_result():
    broker_result = BrokerResult(
        equity_curve=pd.DataFrame(
            [{"date": pd.Timestamp("2025-01-03"), "equity": 100100.0, "cash": 80000.0}]
        ),
        positions=pd.DataFrame(
            [{"date": pd.Timestamp("2025-01-03"), "symbol": "000001.SZ", "shares": 2000}]
        ),
        orders=pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2025-01-03"),
                    "symbol": "000001.SZ",
                    "side": "buy",
                    "requested_shares": 2000,
                    "filled_shares": 2000,
                    "price": 10.0,
                    "commission": 5.0,
                    "tax": 0.0,
                    "transfer_fee": 0.2,
                    "slippage_cost": 0.0,
                    "status": "filled",
                    "reason": "",
                }
            ]
        ),
        trades=pd.DataFrame(
            [{"date": pd.Timestamp("2025-01-03"), "symbol": "000001.SZ", "side": "buy", "shares": 2000, "price": 10.0}]
        ),
    )

    result = broker_result_to_execution_result(broker_result, backend_name="legacy")

    assert result.metadata["backend"] == "legacy"
    assert len(result.orders) == 1
