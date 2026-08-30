# Strategy Sell Signal Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the ten sell signals as first-class backtest strategies and provide buy-signal strategies that can exit early when any sell signal triggers.

**Architecture:** Keep the existing legacy signal frame contract (`date`, `symbol`, `target_weight`) and add a new strategy module, `strategies/ten_sell_signals.py`. Sell signals emit `target_weight=0.0`; buy+sell overlay functions reuse the existing buy entry generators and replace fixed holding exits with the earlier of a sell signal or the fixed holding exit.

**Tech Stack:** Python, pandas, pytest, YAML backtest configs, existing `StrategyContext`, `PythonSignalProvider`, and `BrokerEngine` next-open execution.

---

## File Structure

- Create `strategies/ten_sell_signals.py`: sell signal generators, shared helpers, and buy-with-sell-exit generated functions.
- Create `tests/strategies/test_ten_sell_signals.py`: TDD coverage for 10 sell signals, config wiring, and overlay early exits.
- Create `configs/ten_sell_signals/*.yaml`: 10 independent sell signal configs.
- Create `configs/ten_buy_sell_signals/hold_1/*.yaml`, `hold_5/*.yaml`, `hold_20/*.yaml`: 30 overlay configs.
- Do not modify `backtest/broker/engine.py`: existing `target_weight=0.0` already produces sell intents.
- Only modify `strategies/ten_buy_signals.py` if a helper extraction becomes necessary; if so, preserve every existing test.

## Task 1: Add Sell Signal Test Skeleton

**Files:**
- Create: `tests/strategies/test_ten_sell_signals.py`
- Read: `tests/strategies/test_ten_buy_signals.py`

- [ ] **Step 1: Write the failing test module import and helpers**

Create the test module with helpers matching the buy signal tests:

```python
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
```

- [ ] **Step 2: Run test to verify it fails because the module is missing**

Run:

```bash
uv run pytest tests/strategies/test_ten_sell_signals.py -q
```

Expected: collection fails with `FileNotFoundError` or equivalent missing `strategies/ten_sell_signals.py`.

- [ ] **Step 3: Create the minimal module shell**

Create `strategies/ten_sell_signals.py` with:

```python
from __future__ import annotations

import pandas as pd

SIGNAL_COLUMNS = ["date", "symbol", "target_weight"]


def _empty_signals() -> pd.DataFrame:
    return pd.DataFrame(columns=SIGNAL_COLUMNS)
```

- [ ] **Step 4: Run test again**

Run:

```bash
uv run pytest tests/strategies/test_ten_sell_signals.py -q
```

Expected: PASS while the file only contains helpers and no behavior tests yet.

## Task 2: Implement Daily Sell Signals 1, 3, 4, 5, 8, 10

**Files:**
- Modify: `tests/strategies/test_ten_sell_signals.py`
- Modify: `strategies/ten_sell_signals.py`

- [ ] **Step 1: Add failing tests for sell signals 1, 3, 4, 5, 8, and 10**

Add one test per signal:

```python
def test_sell_signal_01_extreme_volume_without_follow_through_emits_exit() -> None:
    closes = [100.0] * 25
    volumes = [1000.0] * 25
    volumes[10] = 5000.0
    bars = _bars(closes, volumes=volumes)

    result = ten_sell_signals.generate_sell_signal_01(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])


def test_sell_signal_03_two_gap_up_low_closes_emits_exit() -> None:
    closes = [100.0] * 8 + [99.0, 98.0]
    opens = [100.0] * 8 + [101.0, 100.0]
    highs = [101.0] * 10
    lows = [99.0] * 8 + [99.0, 98.0]
    bars = _bars(closes, opens=opens, highs=highs, lows=lows)

    result = ten_sell_signals.generate_sell_signal_03(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])


def test_sell_signal_04_gain_then_ma10_turns_down_emits_exit() -> None:
    closes = [100.0] * 15 + [100.0, 110.0, 120.0, 130.0, 140.0, 135.0, 132.0]
    bars = _bars(closes)

    result = ten_sell_signals.generate_sell_signal_04(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])


def test_sell_signal_05_volume_spike_with_long_upper_shadow_emits_exit() -> None:
    closes = [100.0] * 6
    opens = [100.0] * 6
    highs = [101.0] * 5 + [112.0]
    lows = [99.0] * 6
    volumes = [1000.0] * 5 + [3000.0]
    bars = _bars(closes, opens=opens, highs=highs, lows=lows, volumes=volumes)

    result = ten_sell_signals.generate_sell_signal_05(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])


def test_sell_signal_08_twenty_percent_drawdown_from_recent_peak_emits_exit() -> None:
    closes = [100.0] * 20 + [130.0, 104.0]
    bars = _bars(closes)

    result = ten_sell_signals.generate_sell_signal_08(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])


def test_sell_signal_10_breaks_flat_high_voltage_line_for_two_days_emits_exit() -> None:
    closes = [100.0] * 80 + [119.0, 118.0]
    bars = _bars(closes)

    result = ten_sell_signals.generate_sell_signal_10(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest tests/strategies/test_ten_sell_signals.py -q
```

Expected: FAIL with missing `generate_sell_signal_01` and related function attributes.

- [ ] **Step 3: Add shared helpers and daily sell signal implementations**

Implement:

```python
from collections.abc import Callable


BASE_TARGET_WEIGHT = 0.20


def _prepare_daily_bars(context) -> pd.DataFrame:
    bars = context.bars.copy()
    if bars.empty:
        return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "volume"])
    bars["date"] = pd.to_datetime(bars["date"])
    bars = bars[bars["symbol"].isin(context.stock_pool)].copy()
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
    return _with_zero_weights(bars.loc[mask.fillna(False), ["date", "symbol"]])


def _group_transform(bars: pd.DataFrame, column: str, fn: Callable[[pd.Series], pd.Series]) -> pd.Series:
    return bars.groupby("symbol", group_keys=False)[column].transform(fn)


def _ma(bars: pd.DataFrame, column: str, window: int) -> pd.Series:
    return _group_transform(bars, column, lambda series: series.rolling(window, min_periods=window).mean())


def _shift(bars: pd.DataFrame, column: str, periods: int) -> pd.Series:
    return _group_transform(bars, column, lambda series: series.shift(periods))


def _rolling_max(bars: pd.DataFrame, column: str, window: int) -> pd.Series:
    return _group_transform(bars, column, lambda series: series.rolling(window, min_periods=window).max())


def _rolling_min(bars: pd.DataFrame, column: str, window: int) -> pd.Series:
    return _group_transform(bars, column, lambda series: series.rolling(window, min_periods=window).min())


def _close_near_low(bars: pd.DataFrame, threshold: float = 0.10) -> pd.Series:
    span = bars["high"] - bars["low"]
    return (span > 0) & (((bars["close"] - bars["low"]) / span) <= threshold)
```

Then implement the six signal functions using the approved design formulas.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```bash
uv run pytest tests/strategies/test_ten_sell_signals.py -q
```

Expected: PASS.

## Task 3: Implement Leader and Weekly Sell Signals 2, 6, 7

**Files:**
- Modify: `tests/strategies/test_ten_sell_signals.py`
- Modify: `strategies/ten_sell_signals.py`

- [ ] **Step 1: Add failing tests for sell signals 2, 6, and 7**

Add:

```python
def test_sell_signal_02_two_leaders_weakening_emits_both_exits() -> None:
    leader_1 = _bars([105.0, 104.0, 103.0, 102.0, 101.0], symbol=SYMBOL)
    leader_2 = _bars([55.0, 54.0, 53.0, 52.0, 51.0], symbol=OTHER_SYMBOL)
    bars = pd.concat([leader_1, leader_2], ignore_index=True)

    result = ten_sell_signals.generate_sell_signal_02(_context(bars, [SYMBOL, OTHER_SYMBOL]))

    _assert_exit_on(result, leader_1.iloc[-1]["date"], SYMBOL)
    _assert_exit_on(result, leader_2.iloc[-1]["date"], OTHER_SYMBOL)


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
    lows = [99.0] * 20 + [94.0, 94.0, 94.0, 94.0, 95.0]
    highs = [101.0] * 20 + [104.0, 104.0, 104.0, 104.0, 104.0]
    bars = _bars(closes, start="2025-01-06", highs=highs, lows=lows)

    result = ten_sell_signals.generate_sell_signal_07(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest tests/strategies/test_ten_sell_signals.py -q
```

Expected: FAIL with missing functions 2, 6, and 7.

- [ ] **Step 3: Implement weekly helper and functions**

Add `_weekly_bars()` equivalent to the existing buy strategy implementation, then implement:

- `generate_sell_signal_02`: `context.stock_pool[:2]`, both leaders weak on same date.
- `generate_sell_signal_06`: weekly 20-week extreme volume, then first two following daily bars show weakness.
- `generate_sell_signal_07`: weekly wide range and close at low.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```bash
uv run pytest tests/strategies/test_ten_sell_signals.py -q
```

Expected: PASS.

## Task 4: Implement Double-Top Sell Signal 9

**Files:**
- Modify: `tests/strategies/test_ten_sell_signals.py`
- Modify: `strategies/ten_sell_signals.py`

- [ ] **Step 1: Add failing test for sell signal 9**

Add:

```python
def test_sell_signal_09_double_top_breaks_neckline_emits_exit() -> None:
    closes = [100.0] * 70
    closes[15] = 120.0
    closes[30] = 105.0
    closes[45] = 121.0
    closes[-1] = 104.0
    bars = _bars(closes)

    result = ten_sell_signals.generate_sell_signal_09(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
uv run pytest tests/strategies/test_ten_sell_signals.py::test_sell_signal_09_double_top_breaks_neckline_emits_exit -q
```

Expected: FAIL with missing `generate_sell_signal_09`.

- [ ] **Step 3: Implement double-top scan**

Implement a per-symbol rolling scan:

- Require at least 61 rows up to current row.
- Split the prior 60 rows into left `[t-60, t-30]` and right `[t-29, t]`.
- Find left and right peak indices.
- Require peak heights within 3%.
- Compute neckline as min close between the two peak indices.
- Require neckline drawdown from lower peak at least 10%.
- Require current close below neckline.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```bash
uv run pytest tests/strategies/test_ten_sell_signals.py -q
```

Expected: PASS.

## Task 5: Add Aggregate Sell Signal and Overlay Early Exit

**Files:**
- Modify: `tests/strategies/test_ten_sell_signals.py`
- Modify: `strategies/ten_sell_signals.py`

- [ ] **Step 1: Add failing tests for aggregate and overlay behavior**

Add:

```python
def test_sell_signal_any_deduplicates_earliest_exit_per_symbol_date() -> None:
    closes = [100.0] * 20 + [130.0, 104.0]
    bars = _bars(closes)

    result = ten_sell_signals.generate_sell_signal_any(_context(bars))

    _assert_exit_on(result, bars.iloc[-1]["date"])
    assert result.duplicated(["date", "symbol"]).sum() == 0


def test_buy_with_sell_exit_exits_before_fixed_holding_when_sell_signal_triggers() -> None:
    closes = [100.0] * 80
    closes[34] = 90.0
    closes[45] = 130.0
    closes[46] = 104.0
    volumes = [1000.0] * 80
    volumes[34] = 2500.0
    bars = _bars(closes, volumes=volumes)

    result = ten_sell_signals.generate_buy_signal_01_hold_20_or_sell_signal_exit(_context(bars))

    _assert_exit_on(result, bars.iloc[46]["date"])
    assert not ((result["date"] == bars.iloc[54]["date"]) & (result["target_weight"] == 0.0)).any()
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest tests/strategies/test_ten_sell_signals.py -q
```

Expected: FAIL with missing `generate_sell_signal_any` and overlay function.

- [ ] **Step 3: Implement aggregate and generated overlay functions**

Add:

- `_SELL_SIGNAL_GENERATORS = {1: ..., 10: ...}`
- `generate_sell_signal_any(context)` concatenates all exits, drops duplicate `date/symbol`, sorts.
- Import `strategies.ten_buy_signals` and reuse `_BUY_SIGNAL_GENERATORS`, `_with_target_weights`, and date helpers if acceptable; otherwise duplicate the small fixed-holding orchestration locally.
- Generate `generate_buy_signal_XX_hold_N_or_sell_signal_exit` for `XX=1..10`, `N in (1,5,20)`.

Overlay implementation must:

- Compute entry candidates from the buy entry generator.
- Compute all sell exits once with `generate_sell_signal_any`.
- For each accepted entry window, choose the earliest sell exit date after entry execution and on/before fixed exit signal date.
- Emit entry signal and chosen exit signal.

- [ ] **Step 4: Run tests to verify GREEN**

Run:

```bash
uv run pytest tests/strategies/test_ten_sell_signals.py -q
```

Expected: PASS.

## Task 6: Add Config Files

**Files:**
- Create: `configs/ten_sell_signals/*.yaml`
- Create: `configs/ten_buy_sell_signals/hold_1/*.yaml`
- Create: `configs/ten_buy_sell_signals/hold_5/*.yaml`
- Create: `configs/ten_buy_sell_signals/hold_20/*.yaml`
- Modify: `tests/strategies/test_ten_sell_signals.py`

- [ ] **Step 1: Add failing config tests**

Add:

```python
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
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest tests/strategies/test_ten_sell_signals.py -q
```

Expected: FAIL because config paths do not exist.

- [ ] **Step 3: Create 10 sell configs**

Use the same project/data/execution/metrics/report shape as `configs/ten_buy_signals/buy_signal_01_volume_breakout.yaml`, changing:

- `project.name` to `ten-sell-signal-XX-<slug>`
- `signals.path` to `../../strategies/ten_sell_signals.py`
- `signals.function` to `generate_sell_signal_XX`
- `report.output_dir` to `../../runs/ten_sell_signals/sell_signal_XX`

- [ ] **Step 4: Create 30 overlay configs**

For each holding period and buy signal, mirror the existing `configs/ten_buy_signals/hold_N` structure, changing:

- `project.name` to `ten-buy-signal-XX-<slug>-hold-N-or-sell-exit`
- `signals.path` to `../../../strategies/ten_sell_signals.py`
- `signals.function` to `generate_buy_signal_XX_hold_N_or_sell_signal_exit`
- `report.output_dir` to `../../../runs/ten_buy_sell_signals/hold_N/buy_signal_XX_<slug>`

- [ ] **Step 5: Run config tests to verify GREEN**

Run:

```bash
uv run pytest tests/strategies/test_ten_sell_signals.py -q
```

Expected: PASS.

## Task 7: Regression and Focused Verification

**Files:**
- No new files unless fixes are required.

- [ ] **Step 1: Run strategy tests**

Run:

```bash
uv run pytest tests/strategies/test_ten_buy_signals.py tests/strategies/test_ten_sell_signals.py -q
```

Expected: PASS.

- [ ] **Step 2: Run signal/provider and CLI config-related tests**

Run:

```bash
uv run pytest tests/signals/test_signal_providers.py tests/test_cli_commands.py -q
```

Expected: PASS.

- [ ] **Step 3: Run a full test pass if focused tests are clean**

Run:

```bash
uv run pytest -q
```

Expected: PASS. If full suite is too slow or blocked by environment, record the blocking output.

- [ ] **Step 4: Check git status**

Run:

```bash
git status --short
```

Expected: new/modified files are limited to the design doc, this plan, strategy module, tests, and configs. Existing unrelated `lc_project_settings.json` remains untouched.

## Self-Review

- Spec coverage: independent sell signals, overlay exits, configs, weekly/leader assumptions, and tests are all mapped to tasks.
- Placeholder scan: no TBD/TODO/fill-in-later instructions are required for implementers.
- Type consistency: all generated function names follow `generate_sell_signal_XX` and `generate_buy_signal_XX_hold_N_or_sell_signal_exit`; all outputs use `date`, `symbol`, `target_weight`.
