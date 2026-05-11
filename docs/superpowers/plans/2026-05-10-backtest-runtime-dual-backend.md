# Backtest Runtime Dual Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking; completed items are marked `- [x]`.

**Goal:** Add the missing backtest runtime layer with a shared runner, a legacy BrokerEngine backend, and a native simulation backend that can be verified against the legacy backend.

**Architecture:** `BacktestRunner` owns planning orchestration and delegates execution to an `ExecutionBackend`. `LegacyBrokerExecutionBackend` adapts `TargetPortfolioFrame` to the current `BrokerEngine`; `NativeSimulationBackend` implements the target architecture and must pass parity tests against the legacy backend before it becomes the default.

**Status:** Implemented in the current feature branch. The checked items below are retained as the execution trace for the runtime dual-backend slice.

**Tech Stack:** Python 3.11+, pandas, pydantic v2, pytest via `uv run pytest`.

---

## Scope

This plan implements `docs/superpowers/specs/2026-05-10-backtest-runtime-dual-backend-design.md`.

In scope:

- `BacktestRunner`
- `BacktestRunResult`
- `BacktestExecutionResult`
- `ExecutionBackend`
- `LegacyBrokerExecutionBackend`
- `NativeSimulationBackend`
- target/legacy frame adapters
- parity tests between legacy and native execution backends

Out of scope:

- Rewriting十大买讯 rules
- Live trading adapters
- Tick-level simulation
- Multi-account or multi-strategy runtime
- Shorting, leverage, derivatives, or futures margin

## File Structure

Create:

- `backtest/runtime/__init__.py`: public exports for runtime classes.
- `backtest/runtime/results.py`: `BacktestExecutionResult` and `BacktestRunResult`.
- `backtest/runtime/adapters.py`: conversions between `TargetPortfolioFrame`, legacy `SignalFrame`, `BrokerResult`, and runtime results.
- `backtest/runtime/backend.py`: `ExecutionBackend` protocol and `LegacyBrokerExecutionBackend`.
- `backtest/runtime/runner.py`: `BacktestRunner`, planning modes, and run orchestration.
- `backtest/runtime/native.py`: `NativeSimulationBackend` matching current A-share BrokerEngine semantics.
- `tests/runtime/test_runtime_adapters.py`: adapter tests.
- `tests/runtime/test_legacy_backend.py`: legacy backend tests.
- `tests/runtime/test_native_backend_parity.py`: backend parity tests.
- `tests/runtime/test_backtest_runner.py`: runner tests.

Modify:

- `docs/architecture.md`: add runtime layer to the canonical architecture.
- `docs/data-contracts.md`: document runtime result contracts.

## Shared Test Helpers

Use these helpers in runtime tests instead of inventing slightly different fixtures per file:

```python
from datetime import date

import pandas as pd

from backtest.config.models import ExecutionConfig
from backtest.core.enums import ExecutionTiming


def _bars(
    dates: list[str],
    opens: list[float],
    closes: list[float],
    *,
    symbol: str = "000001.SZ",
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    volumes: list[float] | None = None,
    is_suspended: list[bool] | None = None,
    limit_up: list[float] | None = None,
    limit_down: list[float] | None = None,
) -> pd.DataFrame:
    highs = highs or [max(open_value, close_value) + 1 for open_value, close_value in zip(opens, closes)]
    lows = lows or [min(open_value, close_value) - 1 for open_value, close_value in zip(opens, closes)]
    volumes = volumes or [1000.0] * len(dates)
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "symbol": [symbol] * len(dates),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "amount": [close * volume for close, volume in zip(closes, volumes)],
            "frequency": ["1d"] * len(dates),
            "adjust": ["qfq"] * len(dates),
        }
    )
    if is_suspended is not None:
        frame["is_suspended"] = is_suspended
    if limit_up is not None:
        frame["limit_up"] = limit_up
    if limit_down is not None:
        frame["limit_down"] = limit_down
    return frame


def _execution_config() -> ExecutionConfig:
    return ExecutionConfig(
        timing=ExecutionTiming.NEXT_OPEN,
        initial_cash=100000.0,
        commission_rate=0.0003,
        min_commission=5.0,
        stamp_tax_rate=0.0005,
        transfer_fee_rate=0.00001,
        slippage_rate=0.0,
        board_lot_size=100,
    )
```

## Task 1: Runtime Result Contracts And Adapters

**Files:**
- Create: `tests/runtime/test_runtime_adapters.py`
- Create: `backtest/runtime/results.py`
- Create: `backtest/runtime/adapters.py`
- Create: `backtest/runtime/__init__.py`

- [x] **Step 1: Write failing adapter tests**

Add tests for:

```python
def test_target_portfolio_frame_converts_to_legacy_signal_frame():
    targets = pd.DataFrame(
        {
            "timestamp": ["2025-01-02"],
            "instrument_id": ["000001.SZ"],
            "target_weight": [0.2],
        }
    )

    result = target_portfolio_to_legacy_signal_frame(targets)

    assert list(result.columns) == ["date", "symbol", "target_weight"]
    assert result.iloc[0].to_dict() == {
        "date": pd.Timestamp("2025-01-02"),
        "symbol": "000001.SZ",
        "target_weight": 0.2,
    }
```

and:

```python
def test_broker_result_converts_to_backtest_execution_result():
    broker_result = BrokerResult(
        equity_curve=pd.DataFrame([{"date": pd.Timestamp("2025-01-03"), "equity": 100100.0, "cash": 80000.0}]),
        positions=pd.DataFrame([{"date": pd.Timestamp("2025-01-03"), "symbol": "000001.SZ", "shares": 2000}]),
        orders=pd.DataFrame([{"date": pd.Timestamp("2025-01-03"), "symbol": "000001.SZ", "side": "buy", "requested_shares": 2000, "filled_shares": 2000, "price": 10.0, "commission": 5.0, "tax": 0.0, "transfer_fee": 0.2, "slippage_cost": 0.0, "status": "filled", "reason": ""}]),
        trades=pd.DataFrame([{"date": pd.Timestamp("2025-01-03"), "symbol": "000001.SZ", "side": "buy", "shares": 2000, "price": 10.0}]),
    )

    result = broker_result_to_execution_result(broker_result, backend_name="legacy")

    assert result.metadata["backend"] == "legacy"
    assert len(result.orders) == 1
```

Run:

```bash
uv run pytest tests/runtime/test_runtime_adapters.py -v
```

Expected before implementation:

```text
ModuleNotFoundError: No module named 'backtest.runtime'
```

- [x] **Step 2: Implement `BacktestExecutionResult`**

Create a frozen dataclass:

```python
@dataclass(frozen=True)
class BacktestExecutionResult:
    equity_curve: pd.DataFrame
    positions: pd.DataFrame
    orders: pd.DataFrame
    trades: pd.DataFrame
    metadata: dict[str, Any] = field(default_factory=dict)
```

Preserve DataFrames as copies and copy metadata in `__post_init__`.

- [x] **Step 3: Implement `BacktestRunResult`**

Create a frozen dataclass:

```python
@dataclass(frozen=True)
class BacktestRunResult:
    plans: list[StrategyPlan]
    signals: pd.DataFrame
    targets: pd.DataFrame
    execution: BacktestExecutionResult
    metadata: dict[str, Any] = field(default_factory=dict)
```

Validate `signals` with `validate_signal_score_frame()` and `targets` with `validate_target_portfolio_frame()`.

- [x] **Step 4: Implement adapters**

Add:

```python
def target_portfolio_to_legacy_signal_frame(targets: pd.DataFrame) -> pd.DataFrame:
    validated = validate_target_portfolio_frame(targets)
    result = validated.rename(
        columns={"timestamp": "date", "instrument_id": "symbol"}
    )
    return validate_signal_frame(result[["date", "symbol", "target_weight"]])
```

Add:

```python
def broker_result_to_execution_result(
    broker_result: BrokerResult,
    backend_name: str,
) -> BacktestExecutionResult:
    return BacktestExecutionResult(
        equity_curve=broker_result.equity_curve,
        positions=broker_result.positions,
        orders=broker_result.orders,
        trades=broker_result.trades,
        metadata={"backend": backend_name},
    )
```

- [x] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/runtime/test_runtime_adapters.py -v
```

Expected:

```text
2 passed
```

## Task 2: Legacy Broker Execution Backend

**Files:**
- Create: `tests/runtime/test_legacy_backend.py`
- Create: `backtest/runtime/backend.py`
- Modify: `backtest/runtime/__init__.py`

- [x] **Step 1: Write failing legacy backend test**

Use a three-day single-stock fixture:

```python
def test_legacy_backend_executes_target_portfolio_with_broker_engine():
    bars = _bars(
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
    config = _execution_config()

    result = LegacyBrokerExecutionBackend().execute(bars, targets, config)

    assert result.metadata["backend"] == "legacy_broker"
    assert len(result.trades) == 1
    assert result.trades.iloc[0]["side"] == "buy"
    assert len(result.equity_curve) >= 1
```

Run:

```bash
uv run pytest tests/runtime/test_legacy_backend.py -v
```

Expected before implementation:

```text
ImportError: cannot import name 'LegacyBrokerExecutionBackend'
```

- [x] **Step 2: Implement `ExecutionBackend` protocol**

```python
class ExecutionBackend(Protocol):
    name: str

    def execute(
        self,
        bars: pd.DataFrame,
        targets: pd.DataFrame,
        config: ExecutionConfig,
    ) -> BacktestExecutionResult:
        ...
```

- [x] **Step 3: Implement `LegacyBrokerExecutionBackend`**

```python
class LegacyBrokerExecutionBackend:
    name = "legacy_broker"

    def execute(
        self,
        bars: pd.DataFrame,
        targets: pd.DataFrame,
        config: ExecutionConfig,
    ) -> BacktestExecutionResult:
        signals = target_portfolio_to_legacy_signal_frame(targets)
        broker_result = BrokerEngine(config).run(bars, signals)
        return broker_result_to_execution_result(broker_result, backend_name=self.name)
```

- [x] **Step 4: Run focused tests**

Run:

```bash
uv run pytest tests/runtime/test_legacy_backend.py -v
```

Expected:

```text
1 passed
```

## Task 3: Backtest Runner

**Files:**
- Create: `tests/runtime/test_backtest_runner.py`
- Create: `backtest/runtime/runner.py`
- Modify: `backtest/runtime/__init__.py`

- [x] **Step 1: Write failing runner test**

Create a deterministic planner returning one target:

```python
class StaticPlanner(StrategyPlanner):
    def plan(self, context: StrategyContext) -> StrategyPlan:
        signals = pd.DataFrame(
            {
                "signal_time": [pd.Timestamp("2025-01-02")],
                "instrument_id": ["000001.SZ"],
                "score": [1.0],
                "rank": [1],
                "signal_state": ["long_preferred"],
                "confidence": [1.0],
                "horizon": ["1d"],
                "valid_until": [pd.Timestamp("2025-01-02")],
                "reason": ["static"],
            }
        )
        targets = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2025-01-02")],
                "instrument_id": ["000001.SZ"],
                "target_weight": [0.2],
            }
        )
        return StrategyPlan(
            plan_time=pd.Timestamp("2025-01-02").to_pydatetime(),
            signals=signals,
            targets=targets,
            metadata={"planner": "static"},
        )
```

Assert:

```python
def test_backtest_runner_collects_plans_and_executes_backend():
    runner = BacktestRunner(
        planner=StaticPlanner(),
        backend=LegacyBrokerExecutionBackend(),
        execution_config=_execution_config(),
        planning_mode="batch",
    )

    result = runner.run(
        bars=_bars(
            dates=["2025-01-02", "2025-01-03", "2025-01-06"],
            opens=[10.0, 10.0, 11.0],
            closes=[10.0, 11.0, 12.0],
        ),
        stock_pool=["000001.SZ"],
        start_date="2025-01-02",
        end_date="2025-01-06",
    )

    assert len(result.plans) == 1
    assert len(result.signals) == 1
    assert len(result.targets) == 1
    assert len(result.execution.trades) == 1
    assert result.metadata["backend"] == "legacy_broker"
```

Run:

```bash
uv run pytest tests/runtime/test_backtest_runner.py -v
```

Expected before implementation:

```text
ImportError: cannot import name 'BacktestRunner'
```

- [x] **Step 2: Implement planning mode literal**

Use:

```python
PlanningMode = Literal["batch", "walk_forward"]
```

- [x] **Step 3: Implement `BacktestRunner.__init__`**

Constructor:

```python
def __init__(
    self,
    planner: StrategyPlanner,
    backend: ExecutionBackend,
    execution_config: ExecutionConfig,
    planning_mode: PlanningMode = "walk_forward",
) -> None:
    ...
```

- [x] **Step 4: Implement batch planning**

For `planning_mode == "batch"`:

```python
context = StrategyContext(
    bars=bars,
    stock_pool=stock_pool,
    start_date=start_date,
    end_date=end_date,
    params={},
)
plans = [self.planner.plan(context)]
```

Merge plan signals and targets with `pd.concat`.

- [x] **Step 5: Implement walk-forward planning**

For `planning_mode == "walk_forward"`:

```python
for decision_time in sorted(bars["date"].drop_duplicates()):
    visible_bars = bars[bars["date"] <= decision_time]
    context = StrategyContext(
        bars=visible_bars,
        stock_pool=stock_pool,
        start_date=start_date,
        end_date=str(pd.Timestamp(decision_time).date()),
        params={},
    )
    plan = self.planner.plan(context)
    current_signals = plan.signals[plan.signals["signal_time"] == decision_time]
    current_targets = plan.targets[plan.targets["timestamp"] == decision_time]
    collect only non-empty current rows
```

If a planner emits no current rows, keep the plan in `plans` only when it has metadata useful for debugging. First implementation can collect only plans with current signals or targets.

- [x] **Step 6: Execute backend and return result**

```python
execution = self.backend.execute(bars=bars, targets=targets, config=self.execution_config)
return BacktestRunResult(
    plans=plans,
    signals=signals,
    targets=targets,
    execution=execution,
    metadata={
        "backend": self.backend.name,
        "planning_mode": self.planning_mode,
    },
)
```

- [x] **Step 7: Run focused tests**

Run:

```bash
uv run pytest tests/runtime/test_backtest_runner.py -v
```

Expected:

```text
1 passed
```

## Task 4: Native Simulation Backend MVP

**Files:**
- Create: `tests/runtime/test_native_backend_parity.py`
- Create: `backtest/runtime/native.py`
- Modify: `backtest/runtime/__init__.py`

- [x] **Step 1: Write failing parity test for simple buy**

```python
def test_native_backend_matches_legacy_for_simple_buy():
    bars = _bars(
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
    config = _execution_config()

    legacy = LegacyBrokerExecutionBackend().execute(bars, targets, config)
    native = NativeSimulationBackend().execute(bars, targets, config)

    assert native.orders[["date", "symbol", "side", "filled_shares", "status"]].to_dict("records") == legacy.orders[["date", "symbol", "side", "filled_shares", "status"]].to_dict("records")
    assert native.trades[["date", "symbol", "side", "shares", "price"]].to_dict("records") == legacy.trades[["date", "symbol", "side", "shares", "price"]].to_dict("records")
    pd.testing.assert_frame_equal(native.equity_curve.reset_index(drop=True), legacy.equity_curve.reset_index(drop=True))
```

Run:

```bash
uv run pytest tests/runtime/test_native_backend_parity.py::test_native_backend_matches_legacy_for_simple_buy -v
```

Expected before implementation:

```text
ImportError: cannot import name 'NativeSimulationBackend'
```

- [x] **Step 2: Implement native backend structure**

Add:

```python
class NativeSimulationBackend:
    name = "native_simulation"

    def execute(
        self,
        bars: pd.DataFrame,
        targets: pd.DataFrame,
        config: ExecutionConfig,
    ) -> BacktestExecutionResult:
        ...
```

Validate:

```python
if config.timing != ExecutionTiming.NEXT_OPEN:
    raise NotImplementedError("NativeSimulationBackend MVP supports only next_open execution")
```

- [x] **Step 3: Implement target scheduling**

Mirror `BrokerEngine`:

```python
for target_date, daily_targets in targets.groupby("timestamp", sort=True):
    execution_date = next date in bars where date > target_date
    scheduled_targets.setdefault(execution_date, []).append(daily_targets)
```

On each execution date:

```python
daily_targets = concat scheduled targets
daily_targets = daily_targets.sort_values(["_target_date", "_sequence"]).drop_duplicates("instrument_id", keep="last")
```

- [x] **Step 4: Implement internal account state**

Use a small internal structure equivalent to `backtest.broker.account.Account`:

```python
cash: float
positions: dict[str, int]
lots: dict[str, list[Lot]]
```

This keeps parity with existing `BrokerEngine` for the MVP. Later tasks can replace this with richer `PortfolioState` accounting.

- [x] **Step 5: Implement intent calculation**

Use the same math as current `BrokerEngine._build_intents`:

```python
equity_before = mark_to_market(account, day_bars, "open", last_close_by_symbol)
target_value = equity_before * target_weight
current_value = position_value(symbol, shares, day_bars, "open", last_close_by_symbol)
delta_value = target_value - current_value
side = "buy" if delta_value > 0 else "sell"
requested_shares = floor(abs(delta_value) / slippage_price / board_lot_size) * board_lot_size
```

Sells must execute before buys.

- [x] **Step 6: Implement execution constraints and accounting**

Match current behavior:

- missing execution bar -> rejected order, reason `missing execution bar`
- suspended -> rejected, reason `suspended`
- buy at or above `limit_up` -> rejected, reason `limit up`
- sell at or below `limit_down` -> rejected, reason `limit down`
- below lot -> rejected, reason `below board lot`
- cash insufficient -> reduce to maximum affordable board lot; if zero, rejected, reason `cash insufficient`
- sell unavailable shares -> rejected, reason `T+1 available shares are zero`

Use existing:

```python
AShareCostModel
FixedRateSlippageModel
```

- [x] **Step 7: Implement equity, positions, orders, trades output**

Output columns must match:

```python
EQUITY_CURVE_COLUMNS
POSITIONS_COLUMNS
ORDERS_COLUMNS
TRADES_COLUMNS
```

- [x] **Step 8: Run simple parity test**

Run:

```bash
uv run pytest tests/runtime/test_native_backend_parity.py::test_native_backend_matches_legacy_for_simple_buy -v
```

Expected:

```text
1 passed
```

## Task 5: Native Backend Parity Coverage

**Files:**
- Modify: `tests/runtime/test_native_backend_parity.py`
- Modify: `backtest/runtime/native.py`

- [x] **Step 1: Add sell/rebalance parity test**

Targets:

```text
2025-01-02 000001.SZ 0.5
2025-01-03 000001.SZ 0.2
```

Assert legacy and native produce the same buy then sell trade sequence.

- [x] **Step 2: Add cash-insufficient parity test**

Use target weight `1.0`, high execution price, and fees so requested shares exceed affordable shares. Assert native and legacy match `filled_shares` and order status.

- [x] **Step 3: Add market constraint parity tests**

Cover:

- suspended buy rejection
- limit-up buy rejection
- limit-down sell rejection
- missing execution bar rejection

- [x] **Step 4: Add T+1 parity test**

Create same-day or next-day sell attempt before shares are available. Assert both backends reject with:

```text
T+1 available shares are zero
```

- [x] **Step 5: Run parity suite**

Run:

```bash
uv run pytest tests/runtime/test_native_backend_parity.py -v
```

Expected:

```text
all parity tests pass
```

## Task 6: Parameterized Runtime End-To-End Tests

**Files:**
- Modify: `tests/runtime/test_backtest_runner.py`

- [x] **Step 1: Parameterize runner backend tests**

Use:

```python
@pytest.mark.parametrize("backend_factory", [
    LegacyBrokerExecutionBackend,
    NativeSimulationBackend,
])
def test_backtest_runner_executes_with_each_backend(backend_factory):
    runner = BacktestRunner(
        planner=StaticPlanner(),
        backend=backend_factory(),
        execution_config=_execution_config(),
        planning_mode="batch",
    )
    result = runner.run(...)
    assert len(result.execution.trades) == 1
```

- [x] **Step 2: Add walk-forward planning test**

Create a planner that emits a target only when the visible bars include `2025-01-02`. Run `planning_mode="walk_forward"` and assert:

```text
planner called once per decision date
only current decision target is collected
execution backend receives exactly one target
```

- [x] **Step 3: Run runner tests**

Run:

```bash
uv run pytest tests/runtime/test_backtest_runner.py -v
```

Expected:

```text
all runner tests pass
```

## Task 7: Documentation Alignment

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/data-contracts.md`

- [x] **Step 1: Update architecture docs**

Add:

```text
BacktestRunner / TradingRuntime
  -> StrategyPlanner
  -> ExecutionBackend
       -> LegacyBrokerExecutionBackend
       -> NativeSimulationBackend
```

Document that `BrokerEngine` is a compatibility execution backend, not the final new-architecture center.

- [x] **Step 2: Update data contracts docs**

Add sections for:

- `BacktestExecutionResult`
- `BacktestRunResult`
- target-to-legacy signal adapter
- backend parity contract

- [x] **Step 3: Search for contradictory language**

Run:

```bash
rg "完整替换 `BrokerEngine`|暂不修改|Out of scope|ExecutionAdapter" docs/superpowers/specs docs/superpowers/plans docs/architecture.md docs/data-contracts.md
```

Expected:

```text
Existing first-phase docs may still say BrokerEngine replacement was out of scope for that phase, but runtime docs must clearly define the new second phase.
```

## Task 8: Verification

**Files:**
- No additional files.

- [x] **Step 1: Run runtime focused tests**

Run:

```bash
uv run pytest tests/runtime -v
```

Expected:

```text
all runtime tests pass
```

- [x] **Step 2: Run related regression tests**

Run:

```bash
uv run pytest tests/broker tests/planning/test_order_planner.py tests/strategy tests/portfolio/test_allocator.py tests/test_engine_e2e.py -v
```

Expected:

```text
all selected tests pass
```

- [x] **Step 3: Run full suite**

Run:

```bash
uv run pytest -v
```

Expected:

```text
all tests pass
```

- [x] **Step 4: Inspect changed files**

Run:

```bash
git status --short
git diff --stat
```

Expected:

```text
Runtime modules, runtime tests, and matching docs are changed. Unrelated data/runs artifacts remain untouched.
```

## Review Gate

Review gate was satisfied before implementation. Keep this plan aligned with:

- `docs/superpowers/specs/2026-05-10-backtest-runtime-dual-backend-design.md`
- `docs/superpowers/plans/2026-05-10-backtest-runtime-dual-backend.md`
