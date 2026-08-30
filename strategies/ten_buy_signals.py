from __future__ import annotations

from collections.abc import Callable

import pandas as pd


SIGNAL_COLUMNS = ["date", "symbol", "target_weight"]
BASE_TARGET_WEIGHT = 0.20
NEAR_MA_TOLERANCE = 0.02
FIXED_HOLDING_DAYS = (1, 5, 20)


def _prepare_daily_bars(context) -> pd.DataFrame:
    bars = context.bars.copy()
    if bars.empty:
        return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "volume"])

    bars["date"] = pd.to_datetime(bars["date"])
    bars = bars[bars["symbol"].isin(context.stock_pool)].copy()
    numeric_columns = ["open", "high", "low", "close", "volume"]
    for column in numeric_columns:
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    return bars.sort_values(["symbol", "date"]).reset_index(drop=True)


def _empty_signals() -> pd.DataFrame:
    return pd.DataFrame(columns=SIGNAL_COLUMNS)


def _with_target_weights(signals: pd.DataFrame) -> pd.DataFrame:
    if signals.empty:
        return _empty_signals()

    result = signals[["date", "symbol"]].drop_duplicates().copy()
    result["date"] = pd.to_datetime(result["date"])
    result = result.sort_values(["date", "symbol"]).reset_index(drop=True)
    same_day_count = result.groupby("date")["symbol"].transform("count")
    result["target_weight"] = (1.0 / same_day_count).clip(upper=BASE_TARGET_WEIGHT)
    return result[SIGNAL_COLUMNS]


def _signals_from_mask(bars: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    return _with_target_weights(bars.loc[mask.fillna(False), ["date", "symbol"]])


def _group_transform(
    bars: pd.DataFrame,
    column: str,
    fn: Callable[[pd.Series], pd.Series],
) -> pd.Series:
    return bars.groupby("symbol", group_keys=False)[column].transform(fn)


def _ma(bars: pd.DataFrame, column: str, window: int) -> pd.Series:
    return _group_transform(bars, column, lambda series: series.rolling(window, min_periods=window).mean())


def _prev_ma(bars: pd.DataFrame, column: str, window: int) -> pd.Series:
    return _group_transform(
        bars,
        column,
        lambda series: series.shift(1).rolling(window, min_periods=window).mean(),
    )


def _prev_max(bars: pd.DataFrame, column: str, window: int) -> pd.Series:
    return _group_transform(
        bars,
        column,
        lambda series: series.shift(1).rolling(window, min_periods=window).max(),
    )


def _prev_min(bars: pd.DataFrame, column: str, window: int) -> pd.Series:
    return _group_transform(
        bars,
        column,
        lambda series: series.shift(1).rolling(window, min_periods=window).min(),
    )


def _rolling_max(bars: pd.DataFrame, column: str, window: int) -> pd.Series:
    return _group_transform(bars, column, lambda series: series.rolling(window, min_periods=window).max())


def _shift(bars: pd.DataFrame, column: str, periods: int) -> pd.Series:
    return _group_transform(bars, column, lambda series: series.shift(periods))


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


def _first_daily_after_weekly_setups(
    daily: pd.DataFrame,
    setup_rows: pd.DataFrame,
    daily_condition: pd.Series,
    *,
    max_calendar_days: int = 7,
) -> pd.DataFrame:
    if setup_rows.empty:
        return _empty_signals()

    daily_condition = daily_condition.fillna(False)
    signal_rows: list[dict[str, object]] = []
    for setup in setup_rows.itertuples(index=False):
        setup_date = pd.Timestamp(setup.date)
        candidate_mask = (
            (daily["symbol"] == setup.symbol)
            & (daily["date"] > setup_date)
            & (daily["date"] <= setup_date + pd.Timedelta(days=max_calendar_days))
            & daily_condition
        )
        candidates = daily.loc[candidate_mask, ["date", "symbol"]].sort_values("date")
        if not candidates.empty:
            signal_rows.append(candidates.iloc[0].to_dict())

    if not signal_rows:
        return _empty_signals()
    return _with_target_weights(pd.DataFrame(signal_rows))


def _first_date_index_after(dates: list[pd.Timestamp], signal_date: pd.Timestamp) -> int | None:
    for index, date_value in enumerate(dates):
        if date_value > signal_date:
            return index
    return None


def _signals_with_fixed_holding(
    context,
    entry_generator: Callable[[object], pd.DataFrame],
    holding_days: int,
) -> pd.DataFrame:
    if holding_days < 1:
        raise ValueError("holding_days must be at least 1")

    daily = _prepare_daily_bars(context)
    entry_candidates = entry_generator(context)
    if daily.empty or entry_candidates.empty:
        return _empty_signals()

    dates_by_symbol = {
        symbol: list(symbol_bars["date"].drop_duplicates().sort_values())
        for symbol, symbol_bars in daily.groupby("symbol", sort=False)
    }
    selected_entries: list[dict[str, object]] = []
    exit_rows: list[dict[str, object]] = []
    active_exit_execution_index_by_symbol: dict[str, int] = {}

    for entry in entry_candidates.sort_values(["date", "symbol"]).itertuples(index=False):
        symbol = entry.symbol
        symbol_dates = dates_by_symbol.get(symbol, [])
        signal_date = pd.Timestamp(entry.date)
        entry_execution_index = _first_date_index_after(symbol_dates, signal_date)
        if entry_execution_index is None:
            continue

        exit_signal_index = entry_execution_index + holding_days - 1
        exit_execution_index = exit_signal_index + 1
        if exit_execution_index >= len(symbol_dates):
            continue

        active_until = active_exit_execution_index_by_symbol.get(symbol, -1)
        if entry_execution_index <= active_until:
            continue

        selected_entries.append({"date": signal_date, "symbol": symbol})
        exit_rows.append(
            {
                "date": symbol_dates[exit_signal_index],
                "symbol": symbol,
                "target_weight": 0.0,
            }
        )
        active_exit_execution_index_by_symbol[symbol] = exit_execution_index

    if not selected_entries:
        return _empty_signals()

    entry_signals = _with_target_weights(pd.DataFrame(selected_entries))
    exit_signals = pd.DataFrame(exit_rows, columns=SIGNAL_COLUMNS)
    return (
        pd.concat([entry_signals, exit_signals], ignore_index=True)
        .sort_values(["date", "symbol"])
        .reset_index(drop=True)
    )


def generate_buy_signal_01(context) -> pd.DataFrame:
    """Volume expands above two times prior 5-day volume while price is below MA30."""
    bars = _prepare_daily_bars(context)
    previous_volume_ma5 = _prev_ma(bars, "volume", 5)
    close_ma30 = _ma(bars, "close", 30)
    mask = (bars["volume"] >= 2.0 * previous_volume_ma5) & (bars["close"] < close_ma30)
    return _signals_from_mask(bars, mask)


def generate_buy_signal_02(context) -> pd.DataFrame:
    """Rising short trend with expanding volume, bought near the 10-day moving average."""
    bars = _prepare_daily_bars(context)
    close = bars["close"]
    up_day = close > _shift(bars, "close", 1)
    consecutive_3_up = (
        up_day
        & _group_transform(bars, "close", lambda series: series.shift(1) > series.shift(2))
        & _group_transform(bars, "close", lambda series: series.shift(2) > series.shift(3))
    )
    four_of_five_up = _group_transform(
        bars,
        "close",
        lambda series: (series > series.shift(1)).rolling(4, min_periods=4).sum() >= 4,
    )
    ma10 = _ma(bars, "close", 10)
    ma10_prev = _shift(pd.DataFrame({"symbol": bars["symbol"], "ma10": ma10}), "ma10", 1)
    volume_expands = bars["volume"] > 1.2 * _shift(bars, "volume", 1)
    near_ma10 = (bars["close"] >= ma10) & (bars["close"] <= ma10 * (1.0 + NEAR_MA_TOLERANCE))
    mask = (consecutive_3_up | four_of_five_up) & (ma10 > ma10_prev) & volume_expands & near_ma10
    return _signals_from_mask(bars, mask)


def generate_buy_signal_03(context) -> pd.DataFrame:
    """Weekly volume contraction and price stabilization, then first daily volume rebound."""
    daily = _prepare_daily_bars(context)
    weekly = _weekly_bars(daily)
    weekly_volume = weekly["volume"]
    weekly_close = weekly["close"]
    weekly_low = weekly["low"]
    weekly_contracts = (weekly_volume < _shift(weekly, "volume", 1)) & (
        _shift(weekly, "volume", 1) < _shift(weekly, "volume", 2)
    )
    weekly_volume_new_low = weekly_volume <= _group_transform(
        weekly,
        "volume",
        lambda series: series.rolling(8, min_periods=8).min(),
    )
    weekly_price_stable = weekly_close >= _shift(weekly, "close", 1)
    weekly_not_new_low = weekly_low >= _prev_min(weekly, "low", 4)
    setup_rows = weekly.loc[
        (weekly_contracts & weekly_volume_new_low & weekly_price_stable & weekly_not_new_low).fillna(False),
        ["date", "symbol"],
    ]

    daily_volume_rebound = (daily["volume"] > 1.5 * _prev_ma(daily, "volume", 5)) & (
        daily["close"] > _shift(daily, "close", 1)
    )
    return _first_daily_after_weekly_setups(daily, setup_rows, daily_volume_rebound)


def generate_buy_signal_04(context) -> pd.DataFrame:
    """Low-price bad-news absorption substitute with two volume-up closes and breakout."""
    bars = _prepare_daily_bars(context)
    close_rises_2 = (bars["close"] > _shift(bars, "close", 1)) & (
        _shift(bars, "close", 1) > _shift(bars, "close", 2)
    )
    volume_up_today = bars["volume"] > 1.5 * _prev_ma(bars, "volume", 20)
    volume_up_yesterday = _shift(bars, "volume", 1) > 1.5 * _prev_ma(bars, "volume", 20).groupby(bars["symbol"]).shift(1)
    below_ma200 = bars["close"] < _ma(bars, "close", 200)
    breakout = bars["close"] > _prev_max(bars, "high", 10)
    mask = close_rises_2 & volume_up_today & volume_up_yesterday & below_ma200 & breakout
    return _signals_from_mask(bars, mask)


def generate_buy_signal_05(context) -> pd.DataFrame:
    """Strong stock continuation breakout after a 20-day 30 percent advance."""
    bars = _prepare_daily_bars(context)
    prior_20_close = _shift(bars, "close", 20)
    prior_gain = bars["close"] / prior_20_close - 1.0
    recent_21_max = _rolling_max(bars, "close", 21)
    drawdown_from_recent_high = (recent_21_max - bars["close"]) / recent_21_max
    close_ma20 = _ma(bars, "close", 20)
    prior_60_high = _prev_max(bars, "close", 60)
    mask = (
        (prior_gain > 0.30)
        & (drawdown_from_recent_high <= 0.15)
        & (bars["close"] >= close_ma20)
        & (bars["close"] > prior_60_high)
    )
    return _signals_from_mask(bars, mask)


def generate_buy_signal_06(context) -> pd.DataFrame:
    """Wide weekly range closing at the high, followed by a pullback near rising MA10."""
    daily = _prepare_daily_bars(context)
    weekly = _weekly_bars(daily)
    ma10 = _ma(daily, "close", 10)
    daily_with_ma = daily[["date", "symbol", "close"]].copy()
    daily_with_ma["ma10"] = ma10
    daily_with_ma["ma10_prev"] = _shift(pd.DataFrame({"symbol": daily["symbol"], "ma10": ma10}), "ma10", 1)
    weekly = weekly.merge(daily_with_ma[["date", "symbol", "ma10", "ma10_prev"]], on=["date", "symbol"], how="left")

    weekly_range = (weekly["high"] - weekly["low"]) / weekly["close"]
    closes_at_weekly_high = weekly["close"] >= weekly["high"] * (1.0 - 1e-9)
    setup_rows = weekly.loc[
        ((weekly_range > 0.07) & closes_at_weekly_high & (weekly["ma10"] > weekly["ma10_prev"])).fillna(False),
        ["date", "symbol"],
    ]

    daily_ma10 = daily_with_ma["ma10"]
    pullback_near_ma10 = (daily["close"] >= daily_ma10) & (
        daily["close"] <= daily_ma10 * (1.0 + NEAR_MA_TOLERANCE)
    )
    return _first_daily_after_weekly_setups(daily, setup_rows, pullback_near_ma10)


def generate_buy_signal_07(context) -> pd.DataFrame:
    """Gap-down reversal after a sharp three-day selloff."""
    bars = _prepare_daily_bars(context)
    sharp_drop = bars["close"] / _shift(bars, "close", 3) - 1.0 < -0.08
    gap_down = bars["open"] < _shift(bars, "low", 1)
    bullish_candle = bars["close"] > bars["open"]
    candle_body = bars["close"] - bars["open"]
    lower_shadow_ratio = (bars[["open", "close"]].min(axis=1) - bars["low"]) / candle_body
    long_lower_shadow = bullish_candle & (lower_shadow_ratio > 0.5)
    limit_up_reversal = bars["close"] >= (_shift(bars, "close", 1) * 1.098).round(2)
    mask = sharp_drop & gap_down & (long_lower_shadow | limit_up_reversal)
    return _signals_from_mask(bars, mask)


def generate_buy_signal_08(context) -> pd.DataFrame:
    """Two weekly up closes with the first up week volume at least 25 percent above prior average."""
    daily = _prepare_daily_bars(context)
    weekly = _weekly_bars(daily)
    two_weekly_up_closes = (_shift(weekly, "close", 1) > _shift(weekly, "close", 2)) & (
        weekly["close"] > _shift(weekly, "close", 1)
    )
    prior_four_week_avg_volume = _group_transform(
        weekly,
        "volume",
        lambda series: series.shift(2).rolling(4, min_periods=4).mean(),
    )
    start_week_volume_expands = _shift(weekly, "volume", 1) >= 1.25 * prior_four_week_avg_volume
    mask = two_weekly_up_closes & start_week_volume_expands
    return _signals_from_mask(weekly, mask)


def generate_buy_signal_09(context) -> pd.DataFrame:
    """First two stock-pool symbols act as sector leaders and strengthen together."""
    daily = _prepare_daily_bars(context)
    leaders = list(context.stock_pool[:2])
    if len(leaders) < 2:
        return _empty_signals()

    leader_bars = daily[daily["symbol"].isin(leaders)].copy()
    up_3pct = leader_bars["close"] / _shift(leader_bars, "close", 1) - 1.0 > 0.03
    consecutive_3_big_up = leader_bars.groupby("symbol", group_keys=False)["close"].transform(
        lambda series: ((series / series.shift(1) - 1.0) > 0.03).rolling(3, min_periods=3).sum() >= 3
    )
    four_up_days = leader_bars.groupby("symbol", group_keys=False)["close"].transform(
        lambda series: (series > series.shift(1)).rolling(4, min_periods=4).sum() >= 4
    )
    five_day_gain = leader_bars["close"] / _shift(leader_bars, "close", 5) - 1.0 > 0.10
    leader_bars["strong"] = (up_3pct & consecutive_3_big_up) | (four_up_days & five_day_gain)

    strong_counts = leader_bars[leader_bars["strong"]].groupby("date")["symbol"].nunique()
    synchronized_dates = set(strong_counts[strong_counts == 2].index)
    signals = leader_bars[leader_bars["date"].isin(synchronized_dates)][["date", "symbol"]]
    return _with_target_weights(signals)


def generate_buy_signal_10(context) -> pd.DataFrame:
    """Oversold below gravity line with volume expansion and a bullish close."""
    bars = _prepare_daily_bars(context)
    ma30 = _ma(bars, "close", 30)
    ma72 = _ma(bars, "close", 72)
    gravity_line = (ma30 + ma72) / 2.0
    oversold = bars["close"] <= 0.8 * gravity_line
    volume_expands = bars["volume"] >= 2.0 * _prev_ma(bars, "volume", 5)
    bullish_close = bars["close"] > bars["open"]
    mask = oversold & volume_expands & bullish_close
    return _signals_from_mask(bars, mask)


_BUY_SIGNAL_GENERATORS = {
    1: generate_buy_signal_01,
    2: generate_buy_signal_02,
    3: generate_buy_signal_03,
    4: generate_buy_signal_04,
    5: generate_buy_signal_05,
    6: generate_buy_signal_06,
    7: generate_buy_signal_07,
    8: generate_buy_signal_08,
    9: generate_buy_signal_09,
    10: generate_buy_signal_10,
}


def generate_buy_signal_any(context) -> pd.DataFrame:
    frames = [generator(context) for generator in _BUY_SIGNAL_GENERATORS.values()]
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


def _make_fixed_holding_generator(
    signal_number: int,
    entry_generator: Callable[[object], pd.DataFrame],
    holding_days: int,
) -> Callable[[object], pd.DataFrame]:
    def generate(context) -> pd.DataFrame:
        return _signals_with_fixed_holding(context, entry_generator, holding_days)

    generate.__name__ = f"generate_buy_signal_{signal_number:02d}_hold_{holding_days}"
    generate.__doc__ = f"Buy signal {signal_number:02d} with a fixed {holding_days}-trading-day holding exit."
    return generate


for _signal_number, _entry_generator in _BUY_SIGNAL_GENERATORS.items():
    for _holding_days in FIXED_HOLDING_DAYS:
        globals()[f"generate_buy_signal_{_signal_number:02d}_hold_{_holding_days}"] = _make_fixed_holding_generator(
            _signal_number,
            _entry_generator,
            _holding_days,
        )

del _signal_number, _entry_generator, _holding_days
