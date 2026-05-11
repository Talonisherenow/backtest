import pandas as pd

from backtest.runtime import LegacyBrokerExecutionBackend, NativeSimulationBackend
from tests.runtime.helpers import bars, execution_config


def _assert_execution_equal(native, legacy) -> None:
    order_columns = ["date", "symbol", "side", "requested_shares", "filled_shares", "price", "status", "reason"]
    trade_columns = ["date", "symbol", "side", "shares", "price"]
    pd.testing.assert_frame_equal(
        native.orders[order_columns].reset_index(drop=True),
        legacy.orders[order_columns].reset_index(drop=True),
    )
    pd.testing.assert_frame_equal(
        native.trades[trade_columns].reset_index(drop=True),
        legacy.trades[trade_columns].reset_index(drop=True),
    )
    pd.testing.assert_frame_equal(
        native.equity_curve.reset_index(drop=True),
        legacy.equity_curve.reset_index(drop=True),
    )


def test_native_backend_matches_legacy_for_simple_buy():
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
    config = execution_config()

    legacy = LegacyBrokerExecutionBackend().execute(bar_frame, targets, config)
    native = NativeSimulationBackend().execute(bar_frame, targets, config)

    _assert_execution_equal(native, legacy)


def test_native_backend_matches_legacy_for_rebalance_sell():
    bar_frame = bars(
        dates=["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"],
        opens=[10.0, 10.0, 11.0, 11.0],
        closes=[10.0, 11.0, 11.0, 11.0],
    )
    targets = pd.DataFrame(
        {
            "timestamp": ["2025-01-02", "2025-01-03"],
            "instrument_id": ["000001.SZ", "000001.SZ"],
            "target_weight": [0.5, 0.2],
        }
    )
    config = execution_config()

    legacy = LegacyBrokerExecutionBackend().execute(bar_frame, targets, config)
    native = NativeSimulationBackend().execute(bar_frame, targets, config)

    _assert_execution_equal(native, legacy)


def test_native_backend_matches_legacy_for_cash_insufficient_rejection():
    bar_frame = bars(
        dates=["2025-01-02", "2025-01-03"],
        opens=[1000.0, 1000.0],
        closes=[1000.0, 1000.0],
    )
    targets = pd.DataFrame(
        {
            "timestamp": ["2025-01-02"],
            "instrument_id": ["000001.SZ"],
            "target_weight": [1.0],
        }
    )
    config = execution_config()

    legacy = LegacyBrokerExecutionBackend().execute(bar_frame, targets, config)
    native = NativeSimulationBackend().execute(bar_frame, targets, config)

    _assert_execution_equal(native, legacy)


def test_native_backend_matches_legacy_for_suspended_buy_rejection():
    bar_frame = bars(
        dates=["2025-01-02", "2025-01-03"],
        opens=[10.0, 10.0],
        closes=[10.0, 10.0],
        is_suspended=[False, True],
    )
    targets = pd.DataFrame(
        {
            "timestamp": ["2025-01-02"],
            "instrument_id": ["000001.SZ"],
            "target_weight": [0.2],
        }
    )
    config = execution_config()

    legacy = LegacyBrokerExecutionBackend().execute(bar_frame, targets, config)
    native = NativeSimulationBackend().execute(bar_frame, targets, config)

    _assert_execution_equal(native, legacy)


def test_native_backend_matches_legacy_for_limit_up_buy_rejection():
    bar_frame = bars(
        dates=["2025-01-02", "2025-01-03"],
        opens=[10.0, 10.0],
        closes=[10.0, 10.0],
        limit_up=[11.0, 10.0],
    )
    targets = pd.DataFrame(
        {
            "timestamp": ["2025-01-02"],
            "instrument_id": ["000001.SZ"],
            "target_weight": [0.2],
        }
    )
    config = execution_config()

    legacy = LegacyBrokerExecutionBackend().execute(bar_frame, targets, config)
    native = NativeSimulationBackend().execute(bar_frame, targets, config)

    _assert_execution_equal(native, legacy)


def test_native_backend_matches_legacy_for_limit_down_sell_rejection():
    bar_frame = bars(
        dates=["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"],
        opens=[10.0, 10.0, 10.0, 9.0],
        closes=[10.0, 10.0, 10.0, 9.0],
        limit_down=[8.9, 8.9, 8.9, 9.0],
    )
    targets = pd.DataFrame(
        {
            "timestamp": ["2025-01-02", "2025-01-06"],
            "instrument_id": ["000001.SZ", "000001.SZ"],
            "target_weight": [0.2, 0.0],
        }
    )
    config = execution_config()

    legacy = LegacyBrokerExecutionBackend().execute(bar_frame, targets, config)
    native = NativeSimulationBackend().execute(bar_frame, targets, config)

    _assert_execution_equal(native, legacy)


def test_native_backend_matches_legacy_for_missing_execution_bar_rejection():
    bar_frame = bars(
        dates=["2025-01-02", "2025-01-03"],
        opens=[10.0, 10.0],
        closes=[10.0, 10.0],
        symbol=["000001.SZ", "000002.SZ"],
    )
    targets = pd.DataFrame(
        {
            "timestamp": ["2025-01-02"],
            "instrument_id": ["000001.SZ"],
            "target_weight": [0.2],
        }
    )
    config = execution_config()

    legacy = LegacyBrokerExecutionBackend().execute(bar_frame, targets, config)
    native = NativeSimulationBackend().execute(bar_frame, targets, config)

    _assert_execution_equal(native, legacy)
