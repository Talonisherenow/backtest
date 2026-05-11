import pandas as pd

from backtest.runtime import LegacyBrokerExecutionBackend
from tests.runtime.helpers import bars, execution_config


def test_legacy_backend_executes_target_portfolio_with_broker_engine():
    bar_frame = bars(
        dates=["2025-01-02", "2025-01-03", "2025-01-06"],
        opens=[10.0, 10.0, 11.0],
        closes=[10.0, 11.0, 12.0],
    )
    targets = pd.DataFrame(
        {
            "timestamp": ["2025-01-02"],
            "instrument_id": ["000001.SZ"],
            "target_weight": [0.2],
        }
    )

    result = LegacyBrokerExecutionBackend().execute(bar_frame, targets, execution_config())

    assert result.metadata["backend"] == "legacy_broker"
    assert len(result.trades) == 1
    assert result.trades.iloc[0]["side"] == "buy"
    assert len(result.equity_curve) >= 1
