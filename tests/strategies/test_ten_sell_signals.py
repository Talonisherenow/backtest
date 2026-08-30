import importlib.util
from pathlib import Path

import pandas as pd

from backtest.config.loader import load_config
from backtest.signals.context import StrategyContext


def _load_strategy_module():
    strategy_path = Path("strategies/ten_sell_signals.py")
    spec = importlib.util.spec_from_file_location("ten_sell_signals", strategy_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ten_sell_signals = _load_strategy_module()

SYMBOL = "000001.SZ"
OTHER_SYMBOL = "600519.SH"
SELL_CASE_DIR = Path("configs/ten_sell_signals")
OVERLAY_CASE_DIR = Path("configs/ten_buy_sell_signals")


def _bars(
    closes: list[float],
    *,
    symbol: str = SYMBOL,
    start: str = "2025-01-01",
    volumes: list[float] | None = None,
    opens: list[float] | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=len(closes))
    volumes = volumes or [1000.0] * len(closes)
    opens = opens or closes
    highs = highs or [max(open_value, close_value) + 1 for open_value, close_value in zip(opens, closes)]
    lows = lows or [min(open_value, close_value) - 1 for open_value, close_value in zip(opens, closes)]
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": [symbol] * len(closes),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "amount": [close * volume for close, volume in zip(closes, volumes)],
            "frequency": ["1d"] * len(closes),
            "adjust": ["qfq"] * len(closes),
        }
    )


def _context(bars: pd.DataFrame, stock_pool: list[str] | None = None) -> StrategyContext:
    return StrategyContext(
        bars=bars,
        stock_pool=stock_pool or [SYMBOL],
        start_date=str(bars["date"].min().date()),
        end_date=str(bars["date"].max().date()),
        params={},
    )


def _assert_exit_on(frame: pd.DataFrame, expected_date: pd.Timestamp, symbol: str = SYMBOL) -> None:
    matched = frame[(frame["date"] == expected_date) & (frame["symbol"] == symbol)]
    assert not matched.empty
    assert matched.iloc[0]["target_weight"] == 0.0


def _assert_no_exit_on(frame: pd.DataFrame, expected_date: pd.Timestamp, symbol: str = SYMBOL) -> None:
    matched = frame[(frame["date"] == expected_date) & (frame["symbol"] == symbol)]
    assert matched.empty


def test_sell_signal_module_shell_exposes_empty_signal_frame() -> None:
    result = ten_sell_signals._empty_signals()

    assert list(result.columns) == ["date", "symbol", "target_weight"]
    assert result.empty


def test_sell_signal_01_extreme_volume_without_follow_through_emits_exit() -> None:
    closes = [100.0] * 25
    volumes = [1000.0] * 25
    volumes[10] = 5000.0
    bars = _bars(closes, volumes=volumes)

    result = ten_sell_signals.generate_sell_signal_01(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])


def test_sell_signal_02_two_leaders_weakening_emits_both_exits() -> None:
    leader_1 = _bars([105.0, 104.0, 103.0, 102.0, 101.0], symbol=SYMBOL)
    leader_2 = _bars([55.0, 54.0, 53.0, 52.0, 51.0], symbol=OTHER_SYMBOL)
    bars = pd.concat([leader_1, leader_2], ignore_index=True)

    result = ten_sell_signals.generate_sell_signal_02(_context(bars, [SYMBOL, OTHER_SYMBOL]))

    _assert_exit_on(result, leader_1.iloc[-1]["date"], SYMBOL)
    _assert_exit_on(result, leader_2.iloc[-1]["date"], OTHER_SYMBOL)


def test_sell_signal_03_two_gap_up_low_closes_emits_exit() -> None:
    closes = [100.0] * 8 + [99.0, 98.0]
    opens = [100.0] * 8 + [101.0, 100.0]
    highs = [101.0] * 10
    lows = [99.0] * 8 + [99.0, 98.0]
    bars = _bars(closes, opens=opens, highs=highs, lows=lows)

    result = ten_sell_signals.generate_sell_signal_03(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])


def test_sell_signal_04_gain_then_ma10_turns_down_emits_exit() -> None:
    closes = [100.0] * 11 + [150.0] + [100.0] * 4 + [110.0, 120.0, 130.0, 140.0, 135.0, 132.0]
    bars = _bars(closes)

    result = ten_sell_signals.generate_sell_signal_04(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])


def test_sell_signal_04_uses_close_low_not_intraday_low() -> None:
    closes = [100.0] * 11 + [150.0] + [100.0] * 4 + [110.0, 120.0, 130.0, 140.0, 130.0, 125.0]
    lows = [close - 1.0 for close in closes]
    lows[5] = 90.0
    bars = _bars(closes, lows=lows)

    result = ten_sell_signals.generate_sell_signal_04(_context(bars))

    _assert_no_exit_on(result, bars.iloc[-1]["date"])


def test_sell_signal_05_volume_spike_with_long_upper_shadow_emits_exit() -> None:
    closes = [100.0] * 6
    opens = [100.0] * 5 + [101.0]
    highs = [101.0] * 5 + [112.0]
    lows = [99.0] * 6
    volumes = [1000.0] * 5 + [3000.0]
    bars = _bars(closes, opens=opens, highs=highs, lows=lows, volumes=volumes)

    result = ten_sell_signals.generate_sell_signal_05(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])


def test_sell_signal_05_down_close_without_low_close_or_long_upper_shadow_does_not_emit() -> None:
    closes = [100.0] * 5 + [104.0]
    opens = [100.0] * 5 + [105.0]
    highs = [101.0] * 5 + [106.0]
    lows = [99.0] * 5 + [100.0]
    volumes = [1000.0] * 5 + [3000.0]
    bars = _bars(closes, opens=opens, highs=highs, lows=lows, volumes=volumes)

    result = ten_sell_signals.generate_sell_signal_05(_context(bars))

    _assert_no_exit_on(result, bars.iloc[-1]["date"])


def test_sell_signal_06_weekly_extreme_volume_then_two_weak_days_emits_exit() -> None:
    closes = [100.0] * 100 + [99.0, 98.0]
    volumes = [1000.0] * 100 + [1000.0, 1000.0]
    for index in range(95, 100):
        volumes[index] = 5000.0
    bars = _bars(closes, start="2025-01-06", volumes=volumes)

    result = ten_sell_signals.generate_sell_signal_06(_context(bars))

    _assert_exit_on(result, bars.iloc[101]["date"])


def test_sell_signal_07_weekly_close_at_low_with_wide_range_emits_exit() -> None:
    closes = [100.0] * 20 + [100.0, 101.0, 102.0, 103.0, 95.0]
    lows = [99.0] * 20 + [95.0, 95.0, 95.0, 95.0, 95.0]
    highs = [101.0] * 20 + [104.0, 104.0, 104.0, 104.0, 104.0]
    bars = _bars(closes, start="2025-01-06", highs=highs, lows=lows)

    result = ten_sell_signals.generate_sell_signal_07(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])


def test_sell_signal_08_twenty_percent_drawdown_from_recent_peak_emits_exit() -> None:
    closes = [100.0] * 20 + [130.0, 104.0]
    bars = _bars(closes)

    result = ten_sell_signals.generate_sell_signal_08(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])


def test_sell_signal_10_rising_high_voltage_line_does_not_emit() -> None:
    closes = [100.0] * 75 + [101.0, 101.0, 101.0, 101.0, 101.0, 120.0, 119.0]
    bars = _bars(closes)

    result = ten_sell_signals.generate_sell_signal_10(_context(bars))

    _assert_no_exit_on(result, bars.iloc[-1]["date"])


def test_sell_signal_10_breaks_flat_high_voltage_line_for_two_days_emits_exit() -> None:
    closes = [100.0] * 72 + [130.0] * 5 + [100.0] * 5
    bars = _bars(closes)

    result = ten_sell_signals.generate_sell_signal_10(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])


def test_sell_signal_09_double_top_breaks_neckline_emits_exit() -> None:
    closes = [100.0] * 70
    closes[15] = 120.0
    for index in range(16, 45):
        closes[index] = 110.0 if index != 30 else 105.0
    closes[45] = 121.0
    closes[-1] = 104.0
    bars = _bars(closes)

    result = ten_sell_signals.generate_sell_signal_09(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])


def test_sell_signal_any_deduplicates_earliest_exit_per_symbol_date() -> None:
    closes = [100.0] * 20 + [130.0, 104.0]
    bars = _bars(closes)

    result = ten_sell_signals.generate_sell_signal_any(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])
    assert result.duplicated(["date", "symbol"]).sum() == 0


def test_buy_with_sell_exit_exits_before_fixed_holding_when_sell_signal_triggers() -> None:
    closes = [100.0] * 80
    closes[34] = 90.0
    for index in range(35, 46):
        closes[index] = 90.0 + ((130.0 - 90.0) * (index - 35) / 10)
    closes[46] = 104.0
    for index in range(47, 80):
        closes[index] = 104.0
    volumes = [1000.0] * 80
    volumes[34] = 2500.0
    bars = _bars(closes, volumes=volumes)
    context = _context(bars)

    result = ten_sell_signals.generate_buy_signal_01_hold_20_or_sell_signal_exit(context)
    fixed_result = ten_sell_signals.buy.generate_buy_signal_01_hold_20(context)

    entry_date = bars.iloc[34]["date"]
    fixed_exit_date = bars.iloc[54]["date"]
    exit_rows = result[result["target_weight"] == 0.0]

    assert len(exit_rows) == 1
    assert exit_rows.iloc[0]["date"] > entry_date
    assert exit_rows.iloc[0]["date"] < fixed_exit_date
    _assert_exit_on(fixed_result, fixed_exit_date)


def test_ten_sell_signal_configs_point_to_available_strategy_functions() -> None:
    config_paths = sorted(SELL_CASE_DIR.glob("sell_signal_*.yaml"))

    assert len(config_paths) == 10
    for config_path in config_paths:
        config = load_config(config_path)
        assert config.signals.type == "python"
        assert config.signals.path.resolve() == (Path.cwd() / "strategies/ten_sell_signals.py").resolve()
        assert hasattr(ten_sell_signals, config.signals.function)


def test_buy_sell_overlay_configs_point_to_available_strategy_functions() -> None:
    config_paths = sorted(OVERLAY_CASE_DIR.glob("hold_*/buy_signal_*.yaml"))

    assert len(config_paths) == 30
    for config_path in config_paths:
        config = load_config(config_path)
        assert config.signals.type == "python"
        assert config.signals.path.resolve() == (Path.cwd() / "strategies/ten_sell_signals.py").resolve()
        assert hasattr(ten_sell_signals, config.signals.function)
