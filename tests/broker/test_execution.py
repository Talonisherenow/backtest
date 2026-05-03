import pandas as pd
import pytest

from backtest.broker.engine import BrokerEngine
from backtest.config.models import ExecutionConfig


def make_execution_config(**overrides) -> ExecutionConfig:
    values = {
        "timing": "next_open",
        "initial_cash": 100000,
        "commission_rate": 0.0003,
        "min_commission": 5,
        "stamp_tax_rate": 0.0005,
        "transfer_fee_rate": 0.00001,
        "slippage_rate": 0.0,
        "board_lot_size": 100,
    }
    values.update(overrides)
    return ExecutionConfig(**values)


def make_bars(**overrides) -> pd.DataFrame:
    values = {
        "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
        "symbol": ["000001.SZ", "000001.SZ"],
        "open": [10.0, 10.0],
        "high": [10.5, 10.5],
        "low": [9.5, 9.5],
        "close": [10.0, 10.0],
        "volume": [10000, 10000],
        "amount": [100000, 100000],
        "frequency": ["1d", "1d"],
        "adjust": ["qfq", "qfq"],
    }
    values.update(overrides)
    return pd.DataFrame(values)


def test_broker_buys_in_board_lots_at_next_open():
    bars = make_bars()
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02"]),
            "symbol": ["000001.SZ"],
            "target_weight": [0.101],
        }
    )

    result = BrokerEngine(make_execution_config()).run(bars=bars, signals=signals)

    filled = result.orders[result.orders["status"] == "filled"].iloc[0]
    assert filled["filled_shares"] == 1000
    assert filled["transfer_fee"] == 0.1
    assert result.equity_curve.iloc[0]["cash"] == pytest.approx(89994.9)
    assert result.positions.iloc[-1]["shares"] == 1000


def test_broker_cash_limited_buy_fills_affordable_board_lot_with_actual_fees():
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2025-01-02",
                    "2025-01-02",
                    "2025-01-03",
                    "2025-01-03",
                    "2025-01-06",
                    "2025-01-06",
                ]
            ),
            "symbol": ["000001.SZ", "000002.SZ", "000001.SZ", "000002.SZ", "000001.SZ", "000002.SZ"],
            "open": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            "high": [10.5, 10.5, 10.5, 10.5, 10.5, 10.5],
            "low": [9.5, 9.5, 9.5, 9.5, 9.5, 9.5],
            "close": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            "volume": [10000, 10000, 10000, 10000, 10000, 10000],
            "amount": [100000, 100000, 100000, 100000, 100000, 100000],
            "frequency": ["1d", "1d", "1d", "1d", "1d", "1d"],
            "adjust": ["qfq", "qfq", "qfq", "qfq", "qfq", "qfq"],
        }
    )
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "symbol": ["000002.SZ", "000001.SZ"],
            "target_weight": [0.91, 0.5],
        }
    )

    result = BrokerEngine(make_execution_config(initial_cash=11010.11, stamp_tax_rate=0.0)).run(
        bars=bars,
        signals=signals,
    )

    cash_limited_buy = result.orders[
        (result.orders["date"] == pd.Timestamp("2025-01-06")) & (result.orders["symbol"] == "000001.SZ")
    ].iloc[0]
    assert cash_limited_buy["status"] == "adjusted"
    assert cash_limited_buy["filled_shares"] == 100
    assert result.equity_curve.iloc[-1]["cash"] == pytest.approx(0.0)


def test_broker_collapses_same_signal_day_targets_to_latest_target():
    bars = make_bars()
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-02"]),
            "symbol": ["000001.SZ", "000001.SZ"],
            "target_weight": [0.2, 0.0],
        }
    )

    result = BrokerEngine(make_execution_config()).run(bars=bars, signals=signals)

    assert result.orders.empty
    assert result.positions.empty
    assert result.equity_curve.iloc[0]["cash"] == pytest.approx(100000.0)


def test_broker_rejects_buy_when_next_open_is_limit_up():
    bars = make_bars(limit_up=[11.0, 10.0])
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02"]),
            "symbol": ["000001.SZ"],
            "target_weight": [0.2],
        }
    )

    result = BrokerEngine(make_execution_config()).run(bars=bars, signals=signals)

    rejected = result.orders[result.orders["status"] == "rejected"].iloc[0]
    assert rejected["side"] == "buy"
    assert rejected["transfer_fee"] == 0.0
    assert "limit up" in rejected["reason"]


def test_broker_rejects_buy_when_execution_bar_is_suspended():
    bars = make_bars(is_suspended=[False, True])
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02"]),
            "symbol": ["000001.SZ"],
            "target_weight": [0.2],
        }
    )

    result = BrokerEngine(make_execution_config()).run(bars=bars, signals=signals)

    rejected = result.orders[result.orders["status"] == "rejected"].iloc[0]
    assert rejected["side"] == "buy"
    assert "suspended" in rejected["reason"]


def test_broker_rejects_signal_when_execution_bar_is_missing():
    bars = make_bars(symbol=["000001.SZ", "000002.SZ"])
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02"]),
            "symbol": ["000001.SZ"],
            "target_weight": [0.2],
        }
    )

    result = BrokerEngine(make_execution_config()).run(bars=bars, signals=signals)

    rejected = result.orders[result.orders["status"] == "rejected"].iloc[0]
    assert rejected["symbol"] == "000001.SZ"
    assert "missing execution bar" in rejected["reason"]


def test_broker_rejects_sell_when_next_open_is_limit_down_after_t_plus_one():
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]),
            "symbol": ["000001.SZ", "000001.SZ", "000001.SZ", "000001.SZ"],
            "open": [10.0, 10.0, 10.0, 9.0],
            "high": [10.5, 10.5, 10.5, 9.5],
            "low": [9.5, 9.5, 9.5, 8.5],
            "close": [10.0, 10.0, 10.0, 9.0],
            "volume": [10000, 10000, 10000, 10000],
            "amount": [100000, 100000, 100000, 90000],
            "frequency": ["1d", "1d", "1d", "1d"],
            "adjust": ["qfq", "qfq", "qfq", "qfq"],
            "limit_down": [8.9, 8.9, 8.9, 9.0],
        }
    )
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-06"]),
            "symbol": ["000001.SZ", "000001.SZ"],
            "target_weight": [0.2, 0.0],
        }
    )

    result = BrokerEngine(make_execution_config()).run(bars=bars, signals=signals)

    rejected = result.orders[result.orders["status"] == "rejected"].iloc[0]
    assert rejected["side"] == "sell"
    assert "limit down" in rejected["reason"]


def test_broker_marks_equity_daily_after_first_execution_day():
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            "symbol": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "open": [10.0, 10.0, 12.0],
            "high": [10.5, 10.5, 12.5],
            "low": [9.5, 9.5, 11.5],
            "close": [10.0, 10.0, 12.0],
            "volume": [10000, 10000, 10000],
            "amount": [100000, 100000, 120000],
            "frequency": ["1d", "1d", "1d"],
            "adjust": ["qfq", "qfq", "qfq"],
        }
    )
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02"]),
            "symbol": ["000001.SZ"],
            "target_weight": [0.101],
        }
    )

    result = BrokerEngine(make_execution_config()).run(bars=bars, signals=signals)

    assert result.equity_curve["date"].tolist() == pd.to_datetime(["2025-01-03", "2025-01-06"]).tolist()
    assert result.equity_curve.iloc[-1]["equity"] == pytest.approx(101994.9)


def test_broker_sizes_rebalance_from_execution_open_not_same_day_close():
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            "symbol": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "open": [10.0, 10.0, 10.0],
            "high": [10.5, 10.5, 100.0],
            "low": [9.5, 9.5, 9.5],
            "close": [10.0, 10.0, 100.0],
            "volume": [10000, 10000, 10000],
            "amount": [100000, 100000, 1000000],
            "frequency": ["1d", "1d", "1d"],
            "adjust": ["qfq", "qfq", "qfq"],
        }
    )
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "symbol": ["000001.SZ", "000001.SZ"],
            "target_weight": [0.5, 0.25],
        }
    )

    result = BrokerEngine(
        make_execution_config(commission_rate=0.0, min_commission=0.0, stamp_tax_rate=0.0, transfer_fee_rate=0.0)
    ).run(bars=bars, signals=signals)

    rebalance_order = result.orders[result.orders["date"] == pd.Timestamp("2025-01-06")].iloc[0]
    assert rebalance_order["side"] == "sell"
    assert rebalance_order["requested_shares"] == 2500
    assert rebalance_order["filled_shares"] == 2500


def test_broker_executes_same_day_rebalance_sells_before_buys():
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2025-01-02",
                    "2025-01-02",
                    "2025-01-03",
                    "2025-01-03",
                    "2025-01-06",
                    "2025-01-06",
                ]
            ),
            "symbol": ["000001.SZ", "000002.SZ", "000001.SZ", "000002.SZ", "000001.SZ", "000002.SZ"],
            "open": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            "high": [10.5, 10.5, 10.5, 10.5, 10.5, 10.5],
            "low": [9.5, 9.5, 9.5, 9.5, 9.5, 9.5],
            "close": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            "volume": [10000, 10000, 10000, 10000, 10000, 10000],
            "amount": [100000, 100000, 100000, 100000, 100000, 100000],
            "frequency": ["1d", "1d", "1d", "1d", "1d", "1d"],
            "adjust": ["qfq", "qfq", "qfq", "qfq", "qfq", "qfq"],
        }
    )
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-03"]),
            "symbol": ["000002.SZ", "000001.SZ", "000002.SZ"],
            "target_weight": [0.8, 0.8, 0.0],
        }
    )

    result = BrokerEngine(
        make_execution_config(commission_rate=0.0, min_commission=0.0, stamp_tax_rate=0.0, transfer_fee_rate=0.0)
    ).run(bars=bars, signals=signals)

    day_orders = result.orders[result.orders["date"] == pd.Timestamp("2025-01-06")]
    assert day_orders["side"].tolist() == ["sell", "buy"]
    buy_order = day_orders[day_orders["symbol"] == "000001.SZ"].iloc[0]
    assert buy_order["status"] == "filled"
    assert buy_order["filled_shares"] == 8000


def test_broker_collapses_same_execution_date_signals_to_latest_target():
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-03", "2025-01-06"]),
            "symbol": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 10.0],
            "high": [10.5, 10.5],
            "low": [9.5, 9.5],
            "close": [10.0, 10.0],
            "volume": [10000, 10000],
            "amount": [100000, 100000],
            "frequency": ["1d", "1d"],
            "adjust": ["qfq", "qfq"],
        }
    )
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-04", "2025-01-05"]),
            "symbol": ["000001.SZ", "000001.SZ"],
            "target_weight": [0.5, 0.0],
        }
    )

    result = BrokerEngine(
        make_execution_config(commission_rate=0.0, min_commission=0.0, stamp_tax_rate=0.0, transfer_fee_rate=0.0)
    ).run(bars=bars, signals=signals)

    filled_buys = result.orders[(result.orders["side"] == "buy") & (result.orders["status"] == "filled")]
    assert filled_buys.empty
    assert result.positions.empty
    assert result.equity_curve.iloc[0]["cash"] == pytest.approx(100000.0)
    assert result.equity_curve.iloc[0]["equity"] == pytest.approx(100000.0)


def test_broker_uses_last_close_when_position_bar_is_missing_from_equity_curve():
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            "symbol": ["000001.SZ", "000001.SZ", "000002.SZ"],
            "open": [10.0, 10.0, 20.0],
            "high": [10.5, 10.5, 20.5],
            "low": [9.5, 9.5, 19.5],
            "close": [10.0, 10.0, 20.0],
            "volume": [10000, 10000, 10000],
            "amount": [100000, 100000, 200000],
            "frequency": ["1d", "1d", "1d"],
            "adjust": ["qfq", "qfq", "qfq"],
        }
    )
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02"]),
            "symbol": ["000001.SZ"],
            "target_weight": [0.5],
        }
    )

    result = BrokerEngine(
        make_execution_config(commission_rate=0.0, min_commission=0.0, stamp_tax_rate=0.0, transfer_fee_rate=0.0)
    ).run(bars=bars, signals=signals)

    missing_bar_day = result.equity_curve[result.equity_curve["date"] == pd.Timestamp("2025-01-06")].iloc[0]
    assert missing_bar_day["cash"] == pytest.approx(50000.0)
    assert missing_bar_day["equity"] == pytest.approx(100000.0)


def test_broker_rejects_missing_execution_bar_with_sell_side_for_existing_position():
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            "symbol": ["000001.SZ", "000001.SZ", "000002.SZ"],
            "open": [10.0, 10.0, 20.0],
            "high": [10.5, 10.5, 20.5],
            "low": [9.5, 9.5, 19.5],
            "close": [10.0, 10.0, 20.0],
            "volume": [10000, 10000, 10000],
            "amount": [100000, 100000, 200000],
            "frequency": ["1d", "1d", "1d"],
            "adjust": ["qfq", "qfq", "qfq"],
        }
    )
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "symbol": ["000001.SZ", "000001.SZ"],
            "target_weight": [0.5, 0.0],
        }
    )

    result = BrokerEngine(
        make_execution_config(commission_rate=0.0, min_commission=0.0, stamp_tax_rate=0.0, transfer_fee_rate=0.0)
    ).run(bars=bars, signals=signals)

    rejected = result.orders[result.orders["date"] == pd.Timestamp("2025-01-06")].iloc[0]
    assert rejected["side"] == "sell"
    assert "missing execution bar" in rejected["reason"]


def test_broker_rejects_buy_when_slippage_price_crosses_limit_up():
    bars = make_bars(limit_up=[11.0, 10.1])
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02"]),
            "symbol": ["000001.SZ"],
            "target_weight": [0.2],
        }
    )

    result = BrokerEngine(
        make_execution_config(
            commission_rate=0.0,
            min_commission=0.0,
            stamp_tax_rate=0.0,
            transfer_fee_rate=0.0,
            slippage_rate=0.02,
        )
    ).run(bars=bars, signals=signals)

    rejected = result.orders[result.orders["status"] == "rejected"].iloc[0]
    assert rejected["side"] == "buy"
    assert "limit up" in rejected["reason"]


@pytest.mark.parametrize(
    "signals",
    [
        pd.DataFrame(columns=["date", "symbol", "target_weight"]),
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-03"]),
                "symbol": ["000001.SZ"],
                "target_weight": [0.2],
            }
        ),
    ],
)
def test_broker_result_empty_frames_keep_stable_columns(signals):
    result = BrokerEngine(make_execution_config()).run(bars=make_bars(), signals=signals)

    assert result.equity_curve.columns.tolist() == ["date", "equity", "cash"]
    assert result.positions.columns.tolist() == ["date", "symbol", "shares"]
    assert result.orders.columns.tolist() == [
        "date",
        "symbol",
        "side",
        "requested_shares",
        "filled_shares",
        "price",
        "commission",
        "tax",
        "transfer_fee",
        "slippage_cost",
        "status",
        "reason",
    ]
    assert result.trades.columns.tolist() == ["date", "symbol", "side", "shares", "price"]
