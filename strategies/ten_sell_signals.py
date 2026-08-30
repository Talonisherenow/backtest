from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from backtest.signals.context import StrategyContext


def _load_buy_signals_module():
    strategy_path = Path(__file__).with_name("ten_buy_signals.py")
    spec = importlib.util.spec_from_file_location("ten_buy_signals", strategy_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load buy signals module: {strategy_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


buy = _load_buy_signals_module()

SIGNAL_COLUMNS = ["date", "symbol", "target_weight"]
FIXED_HOLDING_DAYS = (1, 5, 20)


def _empty_signals() -> pd.DataFrame:
    return pd.DataFrame(columns=SIGNAL_COLUMNS)


def _prepare_daily_bars(context: StrategyContext) -> pd.DataFrame:
    bars = context.bars.copy()
    if bars.empty:
        return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "volume"])

    bars["date"] = pd.to_datetime(bars["date"])
    if "frequency" in bars.columns:
        bars = bars[bars["frequency"] == "1d"]
    if context.stock_pool:
        bars = bars[bars["symbol"].isin(context.stock_pool)]

    for column in ["open", "high", "low", "close", "volume"]:
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    return bars.sort_values(["symbol", "date"]).reset_index(drop=True)


def _with_zero_weights(signals: pd.DataFrame) -> pd.DataFrame:
    if signals.empty:
        return _empty_signals()
    result = signals[["date", "symbol"]].drop_duplicates().copy()
    result["date"] = pd.to_datetime(result["date"])
    result["target_weight"] = 0.0
    return result.sort_values(["date", "symbol"]).reset_index(drop=True)[SIGNAL_COLUMNS]


def _signals_from_mask(bars: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    if bars.empty:
        return _empty_signals()
    matched = bars.loc[mask.fillna(False).to_numpy(), ["date", "symbol"]]
    return _with_zero_weights(matched)


def _group_transform(bars: pd.DataFrame, column: str, transform) -> pd.Series:
    return bars.groupby("symbol", group_keys=False)[column].transform(transform)


def _ma(bars: pd.DataFrame, column: str, window: int) -> pd.Series:
    return _group_transform(bars, column, lambda series: series.rolling(window, min_periods=window).mean())


def _shift(bars: pd.DataFrame, column: str | pd.Series, periods: int = 1) -> pd.Series:
    if isinstance(column, str):
        return _group_transform(bars, column, lambda series: series.shift(periods))
    return column.groupby(bars["symbol"], group_keys=False).shift(periods)


def _rolling_max(bars: pd.DataFrame, column: str, window: int) -> pd.Series:
    return _group_transform(bars, column, lambda series: series.rolling(window, min_periods=window).max())


def _rolling_min(bars: pd.DataFrame, column: str, window: int) -> pd.Series:
    return _group_transform(bars, column, lambda series: series.rolling(window, min_periods=window).min())


def _close_near_low(bars: pd.DataFrame) -> pd.Series:
    day_range = bars["high"] - bars["low"]
    return (day_range > 0) & (((bars["close"] - bars["low"]) / day_range) <= 0.1)


def _weekly_bars(daily: pd.DataFrame) -> pd.DataFrame:
    weekly_frames: list[pd.DataFrame] = []
    for symbol, symbol_bars in daily.groupby("symbol", sort=False):
        indexed = symbol_bars.copy()
        indexed["_trade_date"] = indexed["date"]
        indexed = indexed.set_index("date")
        weekly = indexed.resample("W-FRI").agg(
            {
                "_trade_date": "last",
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        weekly = weekly.dropna(subset=["_trade_date", "open", "close"])
        weekly = weekly.rename(columns={"_trade_date": "date"}).reset_index(drop=True)
        weekly["symbol"] = symbol
        weekly_frames.append(weekly)

    if not weekly_frames:
        return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "volume"])
    return pd.concat(weekly_frames, ignore_index=True).sort_values(["symbol", "date"]).reset_index(drop=True)


def _leader_weakness_mask(bars: pd.DataFrame) -> pd.Series:
    down_day = bars["close"] < _shift(bars, "close", 1)
    consecutive_3_down = (
        down_day
        & _group_transform(bars, "close", lambda series: series.shift(1) < series.shift(2))
        & _group_transform(bars, "close", lambda series: series.shift(2) < series.shift(3))
    )
    four_of_five_down = _group_transform(
        bars,
        "close",
        lambda series: (series < series.shift(1)).rolling(4, min_periods=4).sum() >= 4,
    )
    return consecutive_3_down | four_of_five_down


def generate_sell_signal_01(context: StrategyContext) -> pd.DataFrame:
    bars = _prepare_daily_bars(context)
    recent_volume_max = _rolling_max(bars, "volume", 10)
    previous_volume_max = _shift(bars, recent_volume_max, 10)
    return _signals_from_mask(bars, recent_volume_max < previous_volume_max)


def generate_sell_signal_02(context: StrategyContext) -> pd.DataFrame:
    daily = _prepare_daily_bars(context)
    leaders = list(context.stock_pool[:2])
    if len(leaders) < 2:
        return _empty_signals()

    leader_bars = daily[daily["symbol"].isin(leaders)].copy()
    leader_bars["weak"] = _leader_weakness_mask(leader_bars)
    weak_counts = leader_bars[leader_bars["weak"]].groupby("date")["symbol"].nunique()
    synchronized_dates = set(weak_counts[weak_counts == 2].index)
    signals = leader_bars[leader_bars["date"].isin(synchronized_dates)][["date", "symbol"]]
    return _with_zero_weights(signals)


def generate_sell_signal_03(context: StrategyContext) -> pd.DataFrame:
    bars = _prepare_daily_bars(context)
    gap_up = bars["open"] > _shift(bars, "close", 1)
    low_close = _close_near_low(bars)
    two_day_pattern = gap_up & low_close & _shift(bars, gap_up & low_close, 1)
    return _signals_from_mask(bars, two_day_pattern)


def generate_sell_signal_04(context: StrategyContext) -> pd.DataFrame:
    bars = _prepare_daily_bars(context)
    recent_low = _rolling_min(bars, "close", 21)
    ma10 = _ma(bars, "close", 10)
    gain_from_low = (bars["close"] / recent_low) - 1
    ma10_turns_down = ma10 < _shift(bars, ma10, 1)
    return _signals_from_mask(bars, (gain_from_low >= 0.3) & ma10_turns_down)


def generate_sell_signal_05(context: StrategyContext) -> pd.DataFrame:
    bars = _prepare_daily_bars(context)
    volume_spike = bars["volume"] >= (2 * _ma(bars, "volume", 5))
    closes_near_low = _close_near_low(bars)
    body = (bars["close"] - bars["open"]).abs()
    upper_shadow = bars["high"] - bars[["open", "close"]].max(axis=1)
    long_upper_shadow = (body > 0) & ((upper_shadow / body) >= 2)
    return _signals_from_mask(bars, volume_spike & (closes_near_low | long_upper_shadow))


def generate_sell_signal_06(context: StrategyContext) -> pd.DataFrame:
    daily = _prepare_daily_bars(context)
    weekly = _weekly_bars(daily)
    weekly_max_20 = _rolling_max(weekly, "volume", 20)
    setup_rows = weekly.loc[weekly["volume"] >= weekly_max_20, ["date", "symbol"]]

    signal_rows: list[dict[str, object]] = []
    for setup in setup_rows.itertuples(index=False):
        setup_date = pd.Timestamp(setup.date)
        symbol_daily = daily[daily["symbol"] == setup.symbol].sort_values("date")
        setup_close_rows = symbol_daily[symbol_daily["date"] == setup_date]
        if setup_close_rows.empty:
            continue
        setup_close = float(setup_close_rows.iloc[0]["close"])
        following = symbol_daily[symbol_daily["date"] > setup_date].head(2)
        if len(following) < 2:
            continue
        first_day = following.iloc[0]
        second_day = following.iloc[1]
        consecutive_down = (first_day["close"] < setup_close) and (second_day["close"] < first_day["close"])
        cumulative_drop = (second_day["close"] / setup_close) - 1 < -0.03
        if consecutive_down or cumulative_drop:
            signal_rows.append({"date": second_day["date"], "symbol": setup.symbol})

    return _with_zero_weights(pd.DataFrame(signal_rows))


def generate_sell_signal_07(context: StrategyContext) -> pd.DataFrame:
    daily = _prepare_daily_bars(context)
    weekly = _weekly_bars(daily)
    weekly_range = (weekly["high"] - weekly["low"]) / weekly["low"]
    closes_at_low = weekly["close"] <= weekly["low"] * (1.0 + 1e-9)
    mask = closes_at_low & (weekly_range >= 0.05)
    return _signals_from_mask(weekly, mask)


def generate_sell_signal_08(context: StrategyContext) -> pd.DataFrame:
    bars = _prepare_daily_bars(context)
    recent_peak = _rolling_max(bars, "close", 20)
    return _signals_from_mask(bars, bars["close"] <= (recent_peak * 0.8))


def generate_sell_signal_09(context: StrategyContext) -> pd.DataFrame:
    bars = _prepare_daily_bars(context)
    signal_rows: list[dict[str, object]] = []

    for symbol, group in bars.groupby("symbol", sort=False):
        symbol_bars = group.reset_index(drop=True)
        if len(symbol_bars) < 61:
            continue
        for index in range(60, len(symbol_bars)):
            left = symbol_bars.iloc[index - 60 : index - 29]
            right = symbol_bars.iloc[index - 29 : index + 1]
            h1_index = left["close"].idxmax()
            h2_index = right["close"].idxmax()
            h1 = float(symbol_bars.loc[h1_index, "close"])
            h2 = float(symbol_bars.loc[h2_index, "close"])
            if h1 <= 0 or abs(h1 - h2) / h1 > 0.03:
                continue
            peak_start = min(h1_index, h2_index)
            peak_end = max(h1_index, h2_index)
            if peak_start + 1 >= peak_end:
                continue
            between = symbol_bars.loc[peak_start + 1 : peak_end - 1, "close"]
            if between.empty:
                continue
            neckline = float(between.min())
            lower_peak = min(h1, h2)
            if lower_peak <= 0 or (lower_peak - neckline) / lower_peak < 0.10:
                continue
            if float(symbol_bars.iloc[index]["close"]) < neckline:
                signal_rows.append(
                    {
                        "date": symbol_bars.iloc[index]["date"],
                        "symbol": symbol,
                    }
                )

    return _with_zero_weights(pd.DataFrame(signal_rows))


def generate_sell_signal_10(context: StrategyContext) -> pd.DataFrame:
    bars = _prepare_daily_bars(context)
    high_voltage_line = 1.2 * ((_ma(bars, "close", 30) + _ma(bars, "close", 72)) / 2)
    line_was_flat = (high_voltage_line - _shift(bars, high_voltage_line, 5)) <= 0
    below_line = bars["close"] < high_voltage_line
    two_day_break = below_line & _shift(bars, below_line, 1)
    return _signals_from_mask(bars, line_was_flat & two_day_break)


_SELL_SIGNAL_GENERATORS: dict[int, Callable[[StrategyContext], pd.DataFrame]] = {
    1: generate_sell_signal_01,
    2: generate_sell_signal_02,
    3: generate_sell_signal_03,
    4: generate_sell_signal_04,
    5: generate_sell_signal_05,
    6: generate_sell_signal_06,
    7: generate_sell_signal_07,
    8: generate_sell_signal_08,
    9: generate_sell_signal_09,
    10: generate_sell_signal_10,
}


def generate_sell_signal_any(context: StrategyContext) -> pd.DataFrame:
    frames = [generator(context) for generator in _SELL_SIGNAL_GENERATORS.values()]
    non_empty = [frame for frame in frames if not frame.empty]
    if not non_empty:
        return _empty_signals()
    combined = pd.concat(non_empty, ignore_index=True)
    combined["date"] = pd.to_datetime(combined["date"])
    return (
        combined.sort_values(["date", "symbol"])
        .drop_duplicates(["date", "symbol"], keep="first")
        .reset_index(drop=True)[SIGNAL_COLUMNS]
    )


def _signals_with_sell_exit_only(
    context: StrategyContext,
    entry_generator: Callable[[StrategyContext], pd.DataFrame],
) -> pd.DataFrame:
    daily = _prepare_daily_bars(context)
    entry_candidates = entry_generator(context)
    sell_exits = generate_sell_signal_any(context)
    if daily.empty or entry_candidates.empty:
        return _empty_signals()

    dates_by_symbol = {
        symbol: list(symbol_bars["date"].drop_duplicates().sort_values())
        for symbol, symbol_bars in daily.groupby("symbol", sort=False)
    }
    exits_by_symbol: dict[str, list[pd.Timestamp]] = {}
    if not sell_exits.empty:
        for symbol, symbol_exits in sell_exits.groupby("symbol", sort=False):
            exits_by_symbol[symbol] = sorted(pd.to_datetime(symbol_exits["date"]).tolist())

    selected_entries: list[dict[str, object]] = []
    exit_rows: list[dict[str, object]] = []
    active_exit_execution_index_by_symbol: dict[str, int] = {}

    for entry in entry_candidates.sort_values(["date", "symbol"]).itertuples(index=False):
        symbol = entry.symbol
        symbol_dates = dates_by_symbol.get(symbol, [])
        signal_date = pd.Timestamp(entry.date)
        entry_execution_index = buy._first_date_index_after(symbol_dates, signal_date)
        if entry_execution_index is None:
            continue

        active_until = active_exit_execution_index_by_symbol.get(symbol, -1)
        if entry_execution_index <= active_until:
            continue

        entry_execution_date = symbol_dates[entry_execution_index]
        chosen_exit_date: pd.Timestamp | None = None
        for exit_date in exits_by_symbol.get(symbol, []):
            if exit_date > entry_execution_date:
                chosen_exit_date = exit_date
                break

        selected_entries.append({"date": signal_date, "symbol": symbol})
        if chosen_exit_date is not None:
            exit_rows.append(
                {
                    "date": chosen_exit_date,
                    "symbol": symbol,
                    "target_weight": 0.0,
                }
            )
            active_exit_execution_index_by_symbol[symbol] = buy._first_date_index_after(
                symbol_dates,
                chosen_exit_date,
            ) or (len(symbol_dates) - 1)
        else:
            active_exit_execution_index_by_symbol[symbol] = len(symbol_dates) - 1

    if not selected_entries:
        return _empty_signals()

    entry_signals = buy._with_target_weights(pd.DataFrame(selected_entries))
    frames = [entry_signals]
    if exit_rows:
        frames.append(pd.DataFrame(exit_rows, columns=SIGNAL_COLUMNS))
    return (
        pd.concat(frames, ignore_index=True)
        .sort_values(["date", "symbol"])
        .reset_index(drop=True)
    )


def _signals_with_sell_exit(
    context: StrategyContext,
    entry_generator: Callable[[StrategyContext], pd.DataFrame],
    holding_days: int,
) -> pd.DataFrame:
    if holding_days < 1:
        raise ValueError("holding_days must be at least 1")

    daily = _prepare_daily_bars(context)
    entry_candidates = entry_generator(context)
    sell_exits = generate_sell_signal_any(context)
    if daily.empty or entry_candidates.empty:
        return _empty_signals()

    dates_by_symbol = {
        symbol: list(symbol_bars["date"].drop_duplicates().sort_values())
        for symbol, symbol_bars in daily.groupby("symbol", sort=False)
    }
    exits_by_symbol: dict[str, list[pd.Timestamp]] = {}
    if not sell_exits.empty:
        for symbol, symbol_exits in sell_exits.groupby("symbol", sort=False):
            exits_by_symbol[symbol] = sorted(pd.to_datetime(symbol_exits["date"]).tolist())

    selected_entries: list[dict[str, object]] = []
    exit_rows: list[dict[str, object]] = []
    active_exit_execution_index_by_symbol: dict[str, int] = {}

    for entry in entry_candidates.sort_values(["date", "symbol"]).itertuples(index=False):
        symbol = entry.symbol
        symbol_dates = dates_by_symbol.get(symbol, [])
        signal_date = pd.Timestamp(entry.date)
        entry_execution_index = buy._first_date_index_after(symbol_dates, signal_date)
        if entry_execution_index is None:
            continue

        fixed_exit_signal_index = entry_execution_index + holding_days - 1
        fixed_exit_execution_index = fixed_exit_signal_index + 1
        if fixed_exit_execution_index >= len(symbol_dates):
            continue

        active_until = active_exit_execution_index_by_symbol.get(symbol, -1)
        if entry_execution_index <= active_until:
            continue

        fixed_exit_date = symbol_dates[fixed_exit_signal_index]
        entry_execution_date = symbol_dates[entry_execution_index]
        chosen_exit_date = fixed_exit_date
        for exit_date in exits_by_symbol.get(symbol, []):
            if exit_date <= entry_execution_date:
                continue
            if exit_date <= fixed_exit_date:
                chosen_exit_date = exit_date
                break

        selected_entries.append({"date": signal_date, "symbol": symbol})
        exit_rows.append(
            {
                "date": chosen_exit_date,
                "symbol": symbol,
                "target_weight": 0.0,
            }
        )
        active_exit_execution_index_by_symbol[symbol] = fixed_exit_execution_index

    if not selected_entries:
        return _empty_signals()

    entry_signals = buy._with_target_weights(pd.DataFrame(selected_entries))
    exit_signals = pd.DataFrame(exit_rows, columns=SIGNAL_COLUMNS)
    return (
        pd.concat([entry_signals, exit_signals], ignore_index=True)
        .sort_values(["date", "symbol"])
        .reset_index(drop=True)
    )


def _make_buy_with_sell_exit_generator(
    signal_number: int,
    holding_days: int,
) -> Callable[[StrategyContext], pd.DataFrame]:
    entry_generator = buy._BUY_SIGNAL_GENERATORS[signal_number]

    def generate(context: StrategyContext) -> pd.DataFrame:
        return _signals_with_sell_exit(context, entry_generator, holding_days)

    generate.__name__ = (
        f"generate_buy_signal_{signal_number:02d}_hold_{holding_days}_or_sell_signal_exit"
    )
    generate.__doc__ = (
        f"Buy signal {signal_number:02d} with fixed {holding_days}-day holding, "
        "or earlier exit when any sell signal triggers."
    )
    return generate


for _signal_number in _SELL_SIGNAL_GENERATORS:
    for _holding_days in FIXED_HOLDING_DAYS:
        globals()[
            f"generate_buy_signal_{_signal_number:02d}_hold_{_holding_days}_or_sell_signal_exit"
        ] = _make_buy_with_sell_exit_generator(_signal_number, _holding_days)


def generate_buy_any_or_sell_signal_exit(context: StrategyContext) -> pd.DataFrame:
    """Enter on any buy signal; exit on any sell signal, otherwise hold."""
    return _signals_with_sell_exit_only(context, buy.generate_buy_signal_any)


del _signal_number, _holding_days
