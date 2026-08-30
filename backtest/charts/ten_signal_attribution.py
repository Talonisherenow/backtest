from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

from backtest.signals.context import StrategyContext

BUY_SIGNAL_LABELS: dict[int, str] = {
    1: "买讯01 旱地拔葱放量",
    2: "买讯02 连续上涨拉回",
    3: "买讯03 周量缩价稳",
    4: "买讯04 利空不跌反涨",
    5: "买讯05 强势股再突破",
    6: "买讯06 周震荡收高均线上翻",
    7: "买讯07 低开高走逆转",
    8: "买讯08 周线连红量增",
    9: "买讯09 板块龙头领涨",
    10: "买讯10 超跌地心引力放量",
}

SELL_SIGNAL_LABELS: dict[int, str] = {
    1: "卖讯01 天量无后续",
    2: "卖讯02 龙头走弱",
    3: "卖讯03 双跳空低收",
    4: "卖讯04 涨幅后MA10拐头",
    5: "卖讯05 放量长上影",
    6: "卖讯06 周量后两日走弱",
    7: "卖讯07 周线低收宽振幅",
    8: "卖讯08 20%回撤",
    9: "卖讯09 双顶破颈线",
    10: "卖讯10 破高压线",
}


def _load_strategy_module(filename: str, module_name: str):
    strategy_path = Path(__file__).resolve().parents[2] / "strategies" / filename
    spec = importlib.util.spec_from_file_location(module_name, strategy_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load strategy module: {strategy_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _signal_date_before_execution(bars: pd.DataFrame, execution_date: pd.Timestamp) -> pd.Timestamp | None:
    dates = sorted(pd.to_datetime(bars["date"].drop_duplicates()))
    execution_date = pd.Timestamp(execution_date).normalize()
    for index, trade_date in enumerate(dates):
        if pd.Timestamp(trade_date).normalize() != execution_date:
            continue
        if index == 0:
            return None
        return pd.Timestamp(dates[index - 1]).normalize()
    return None


def _first_signal_hits(
    context: StrategyContext,
    generators: dict[int, object],
    labels: dict[int, str],
) -> dict[tuple[str, pd.Timestamp], tuple[int, str]]:
    hits: dict[tuple[str, pd.Timestamp], tuple[int, str]] = {}
    for signal_number in sorted(generators):
        generator = generators[signal_number]
        frame = generator(context)
        if frame.empty:
            continue
        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        for row in frame.itertuples(index=False):
            key = (str(row.symbol), pd.Timestamp(row.date))
            if key not in hits:
                hits[key] = (signal_number, labels[signal_number])
    return hits


def attribute_ten_signal_orders(
    *,
    bars: pd.DataFrame,
    orders: pd.DataFrame,
    stock_pool: list[str] | None = None,
) -> pd.DataFrame:
    if orders.empty or bars.empty:
        return orders.copy()

    buy_module = _load_strategy_module("ten_buy_signals.py", "ten_buy_signals_attr")
    sell_module = _load_strategy_module("ten_sell_signals.py", "ten_sell_signals_attr")

    symbols = stock_pool or sorted({str(symbol) for symbol in orders["symbol"].dropna().astype(str)})
    context = StrategyContext(
        bars=bars,
        stock_pool=symbols,
        start_date=pd.to_datetime(bars["date"]).min().date().isoformat(),
        end_date=pd.to_datetime(bars["date"]).max().date().isoformat(),
        params={},
    )
    buy_hits = _first_signal_hits(context, buy_module._BUY_SIGNAL_GENERATORS, BUY_SIGNAL_LABELS)
    sell_hits = _first_signal_hits(context, sell_module._SELL_SIGNAL_GENERATORS, SELL_SIGNAL_LABELS)

    attributed = orders.copy()
    attributed["date"] = pd.to_datetime(attributed["date"])
    signal_ids: list[str] = []
    signal_labels: list[str] = []
    signal_dates: list[str] = []

    for row in attributed.itertuples(index=False):
        side = str(row.side).lower()
        execution_date = pd.Timestamp(row.date).normalize()
        signal_date = _signal_date_before_execution(bars, execution_date)
        if signal_date is None:
            signal_ids.append("")
            signal_labels.append("")
            signal_dates.append("")
            continue

        key = (str(row.symbol), signal_date)
        if side == "buy":
            signal_number, label = buy_hits.get(key, (None, ""))
            prefix = "B"
        elif side == "sell":
            signal_number, label = sell_hits.get(key, (None, ""))
            prefix = "S"
        else:
            signal_number, label = (None, "")
            prefix = ""

        signal_ids.append(f"{prefix}{signal_number:02d}" if signal_number is not None else "")
        signal_labels.append(label)
        signal_dates.append(signal_date.date().isoformat())

    attributed["signal_id"] = signal_ids
    attributed["signal_label"] = signal_labels
    attributed["signal_date"] = signal_dates
    return attributed
