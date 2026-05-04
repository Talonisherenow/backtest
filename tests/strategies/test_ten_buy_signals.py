import importlib.util
from pathlib import Path

import pandas as pd

from backtest.config.loader import load_config
from backtest.signals.context import StrategyContext


def _load_strategy_module():
    strategy_path = Path("strategies/ten_buy_signals.py")
    spec = importlib.util.spec_from_file_location("ten_buy_signals", strategy_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ten_buy_signals = _load_strategy_module()


SYMBOL = "000001.SZ"
OTHER_SYMBOL = "600519.SH"
CASE_DIR = Path("configs/ten_buy_signals")


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


def _assert_signal_on(frame: pd.DataFrame, expected_date: pd.Timestamp, symbol: str = SYMBOL) -> None:
    matched = frame[(frame["date"] == expected_date) & (frame["symbol"] == symbol)]
    assert not matched.empty
    assert 0 < matched.iloc[0]["target_weight"] <= 1


def test_buy_signal_01_volume_breakout_emits_signal() -> None:
    closes = [100.0] * 35
    closes[-1] = 90.0
    volumes = [1000.0] * 35
    volumes[-1] = 2500.0
    bars = _bars(closes, volumes=volumes)

    result = ten_buy_signals.generate_buy_signal_01(_context(bars))

    _assert_signal_on(result, bars.iloc[-1]["date"])


def test_buy_signal_02_rising_price_pullback_emits_signal() -> None:
    closes = [100.0] * 20 + [100.0, 100.1, 100.2, 100.3, 100.4, 100.5]
    volumes = [1000.0] * len(closes)
    volumes[-1] = 1300.0
    bars = _bars(closes, volumes=volumes)

    result = ten_buy_signals.generate_buy_signal_02(_context(bars))

    _assert_signal_on(result, bars.iloc[-1]["date"])


def test_buy_signal_03_weekly_volume_contraction_then_daily_rebound_emits_signal() -> None:
    closes = [100.0] * 55
    volumes = [1000.0] * 55
    for index in range(35, 40):
        volumes[index] = 2000.0
    for index in range(40, 45):
        volumes[index] = 1000.0
    for index in range(45, 50):
        volumes[index] = 500.0
        closes[index] = 101.0
    closes[50] = 102.0
    volumes[50] = 3000.0
    bars = _bars(closes, start="2025-01-06", volumes=volumes)

    result = ten_buy_signals.generate_buy_signal_03(_context(bars))

    _assert_signal_on(result, bars.iloc[50]["date"])


def test_buy_signal_04_bad_news_absorption_breakout_emits_signal() -> None:
    closes = [100.0] * 220
    closes[-12:-2] = [80.0] * 10
    closes[-2:] = [82.0, 85.0]
    volumes = [1000.0] * 220
    volumes[-2:] = [2000.0, 2500.0]
    highs = [close + 1 for close in closes]
    highs[-12:-1] = [84.0] * 11
    highs[-1] = 86.0
    bars = _bars(closes, volumes=volumes, highs=highs)

    result = ten_buy_signals.generate_buy_signal_04(_context(bars))

    _assert_signal_on(result, bars.iloc[-1]["date"])


def test_buy_signal_05_strong_stock_breakout_emits_signal() -> None:
    closes = [100.0] * 70
    closes[-21:-1] = [100.0 + index for index in range(20)]
    closes[-2] = 130.0
    closes[-1] = 132.0
    bars = _bars(closes)

    result = ten_buy_signals.generate_buy_signal_05(_context(bars))

    _assert_signal_on(result, bars.iloc[-1]["date"])


def test_buy_signal_06_weekly_high_close_then_ma_pullback_emits_signal() -> None:
    closes = [100.0] * 45 + [101.0, 102.0, 103.0, 104.0, 105.0, 102.0]
    lows = [close - 1 for close in closes]
    highs = [close + 1 for close in closes]
    lows[45:50] = [97.0] * 5
    highs[45:50] = [105.0] * 5
    highs[49] = 105.0
    bars = _bars(closes, start="2025-01-06", highs=highs, lows=lows)

    result = ten_buy_signals.generate_buy_signal_06(_context(bars))

    _assert_signal_on(result, bars.iloc[-1]["date"])


def test_buy_signal_07_gap_down_reversal_emits_signal() -> None:
    closes = [100.0] * 12
    closes[-4:] = [100.0, 94.0, 91.0, 90.0]
    opens = closes.copy()
    highs = [close + 1 for close in closes]
    lows = [close - 1 for close in closes]
    opens[-1] = 89.0
    highs[-1] = 91.0
    lows[-1] = 85.0
    bars = _bars(closes, opens=opens, highs=highs, lows=lows)

    result = ten_buy_signals.generate_buy_signal_07(_context(bars))

    _assert_signal_on(result, bars.iloc[-1]["date"])


def test_buy_signal_08_two_weekly_up_closes_with_volume_emits_signal() -> None:
    closes = [100.0] * 35
    volumes = [1000.0] * 35
    closes[25:30] = [103.0] * 5
    closes[30:35] = [105.0] * 5
    for index in range(25, 30):
        volumes[index] = 1300.0
    bars = _bars(closes, start="2025-01-06", volumes=volumes)

    result = ten_buy_signals.generate_buy_signal_08(_context(bars))

    _assert_signal_on(result, bars.iloc[34]["date"])


def test_buy_signal_09_two_leaders_strength_emits_both_leaders() -> None:
    leader_1 = _bars([100.0, 104.0, 108.5, 113.0, 118.0], symbol=SYMBOL)
    leader_2 = _bars([50.0, 52.0, 54.2, 56.5, 59.0], symbol=OTHER_SYMBOL)
    bars = pd.concat([leader_1, leader_2], ignore_index=True)

    result = ten_buy_signals.generate_buy_signal_09(_context(bars, [SYMBOL, OTHER_SYMBOL]))

    _assert_signal_on(result, leader_1.iloc[-1]["date"], SYMBOL)
    _assert_signal_on(result, leader_2.iloc[-1]["date"], OTHER_SYMBOL)


def test_buy_signal_10_oversold_gravity_volume_emits_signal() -> None:
    closes = [100.0] * 80
    closes[-1] = 75.0
    opens = closes.copy()
    opens[-1] = 74.0
    volumes = [1000.0] * 80
    volumes[-1] = 2500.0
    bars = _bars(closes, opens=opens, volumes=volumes)

    result = ten_buy_signals.generate_buy_signal_10(_context(bars))

    _assert_signal_on(result, bars.iloc[-1]["date"])


def test_ten_buy_signal_configs_point_to_available_strategy_functions() -> None:
    config_paths = sorted(CASE_DIR.glob("buy_signal_*.yaml"))

    assert len(config_paths) == 10
    for config_path in config_paths:
        config = load_config(config_path)
        assert config.signals.type == "python"
        assert config.signals.path.resolve() == (Path.cwd() / "strategies/ten_buy_signals.py").resolve()
        assert hasattr(ten_buy_signals, config.signals.function)
