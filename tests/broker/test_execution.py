import pandas as pd

from backtest.broker.engine import BrokerEngine
from backtest.config.models import ExecutionConfig


def make_execution_config() -> ExecutionConfig:
    return ExecutionConfig(
        timing="next_open",
        initial_cash=100000,
        commission_rate=0.0003,
        min_commission=5,
        stamp_tax_rate=0.0005,
        slippage_rate=0.0,
        board_lot_size=100,
    )


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
    assert result.positions.iloc[-1]["shares"] == 1000


def test_broker_blocks_same_day_sell_due_to_t_plus_one():
    bars = make_bars()
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-02"]),
            "symbol": ["000001.SZ", "000001.SZ"],
            "target_weight": [0.2, 0.0],
        }
    )

    result = BrokerEngine(make_execution_config()).run(bars=bars, signals=signals)

    rejected = result.orders[result.orders["status"] == "rejected"]
    assert "T+1" in rejected.iloc[0]["reason"]


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
    assert "limit up" in rejected["reason"]
