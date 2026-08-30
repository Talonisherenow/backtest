from pathlib import Path

import pandas as pd

from backtest.charts.ten_signal_attribution import attribute_ten_signal_orders


def test_attribute_ten_signal_orders_maps_execution_to_signal_day() -> None:
    bars = pd.read_parquet(
        Path("data/bars/frequency=1d/adjust=qfq/symbol=000066.SZ/year=2025/bars.parquet")
    )
    bars = pd.concat(
        [
            bars,
            pd.read_parquet(
                Path("data/bars/frequency=1d/adjust=qfq/symbol=000066.SZ/year=2026/bars.parquet")
            ),
        ],
        ignore_index=True,
    )
    orders = pd.read_parquet(
        Path(
            "runs/ten_buy_sell_signals/buy_any_or_sell_exit_000066/"
            "ten-buy-any-or-sell-exit-000066_20260524T160639193205Z/orders.parquet"
        )
    )

    attributed = attribute_ten_signal_orders(bars=bars, orders=orders, stock_pool=["000066.SZ"])
    buys = attributed[attributed["side"] == "buy"]
    sells = attributed[attributed["side"] == "sell"]

    assert len(buys) == 11
    assert len(sells) == 11
    assert buys["signal_id"].str.startswith("B").all()
    assert sells["signal_id"].str.startswith("S").all()
    assert buys["signal_label"].str.startswith("买讯").all()
    assert sells["signal_label"].str.startswith("卖讯").all()
    assert buys["signal_date"].notna().all()
