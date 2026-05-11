# Strategy Planning Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking; completed items are marked `- [x]`.

**Goal:** Implement the first slice of the new strategy architecture: signal generation, portfolio allocation, strategy planning, legacy signal-provider adaptation, and pre-execution signal evaluation.

**Architecture:** Keep the new architecture as the canonical path and integrate old code only through adapters. First add contracts and pure transformation modules, then add `SignalGenerator -> PortfolioAllocator -> StrategyPlanner`; wrap existing `FileSignalProvider` / `PythonSignalProvider` as `LegacyStrategyPlanner`; do not switch the main `BacktestEngine` or rewrite `BrokerEngine` in this phase.

**Status:** Implemented in the current feature branch. The checked items below are retained as the execution trace for the first strategy-planning slice.

**Tech Stack:** Python 3.11+, pandas, pydantic v2, pytest via `uv run pytest`.

---

## Scope

This plan implements only the first phase described in `docs/superpowers/specs/2026-05-10-strategy-planning-architecture-design.md`.

## Naming Alignment

Use these names consistently in code, tests, and documentation:

```text
SignalGenerator
  -> SignalScoreFrame
  Responsibility: generate scores, ranks, and signal states for instruments.

PortfolioAllocator
  -> TargetPortfolioFrame
  Responsibility: convert signal scores into target portfolio weights.

StrategyPlanner
  -> StrategyPlan
  Responsibility: orchestrate SignalGenerator + PortfolioAllocator and return one strategy-stage plan.
```

Use the canonical names above consistently in design, plans, tests, and code.

`SignalGenerator` must not return target weights or order intents. `StrategyPlan` must not contain `OrderIntent`; order creation remains the responsibility of `OrderPlanner`.

In scope:

- `SignalScoreFrame`
- `StrategyPlan`
- `SignalState`
- `SignalGenerator` protocol
- `PortfolioAllocator`
- `StrategyPlanner`
- `LegacyStrategyPlanner`
- `SignalEvaluator`
- Documentation updates for architecture and data contracts

Out of scope:

- Replacing `BacktestEngine`
- Replacing `BrokerEngine`
- Implementing `RiskGate`
- Implementing `ExecutionAdapter`
- Implementing `PortfolioAccounting`
- Implementing real-time scheduler or live broker integration

## File Structure

Create:

- `backtest/strategy/__init__.py`: public exports for strategy contracts, generators, planners, and evaluators.
- `backtest/strategy/contracts.py`: `SignalState`, `SignalScoreFrame` validator, and `StrategyPlan`.
- `backtest/strategy/generator.py`: `SignalGenerator` protocol.
- `backtest/strategy/planner.py`: `StrategyPlanner`, `DefaultStrategyPlanner`, and `LegacyStrategyPlanner`.
- `backtest/strategy/evaluation.py`: `SignalEvaluator`.
- `backtest/portfolio/allocator.py`: `PortfolioAllocationConfig` and `PortfolioAllocator`.
- `tests/strategy/test_strategy_contracts.py`: contract tests.
- `tests/strategy/test_strategy_planner.py`: default and legacy planner tests.
- `tests/strategy/test_signal_evaluator.py`: signal evaluator tests.
- `tests/portfolio/test_allocator.py`: allocator tests.

Modify:

- `backtest/portfolio/__init__.py`: export allocator classes.
- `docs/architecture.md`: distinguish components from data products and summarize the new path.
- `docs/data-contracts.md`: document `SignalScoreFrame`, `TargetPortfolioFrame`, `StrategyPlan`, and allocator behavior.

Do not modify in this phase:

- `backtest/engine.py`
- `backtest/broker/engine.py`
- `backtest/planning/order_planner.py`

## Task 1: Add Signal And Strategy Plan Contracts

**Files:**
- Create: `tests/strategy/test_strategy_contracts.py`
- Create: `backtest/strategy/contracts.py`
- Create: `backtest/strategy/__init__.py`

- [x] **Step 1: Write failing contract tests**

Create tests that cover:

- `validate_signal_score_frame()` normalizes instrument ids and preserves canonical columns.
- invalid `confidence` outside `[0, 1]` is rejected.
- duplicate `signal_time + instrument_id` rows are rejected.
- `StrategyPlan` validates `signals` and `targets`.

Test command:

```bash
uv run pytest tests/strategy/test_strategy_contracts.py -v
```

Expected before implementation:

```text
ModuleNotFoundError: No module named 'backtest.strategy'
```

- [x] **Step 2: Implement `SignalState`**

Add enum values:

```python
class SignalState(StrEnum):
    LONG_PREFERRED = "long_preferred"
    NEUTRAL = "neutral"
    EXIT_PREFERRED = "exit_preferred"
    BLOCKED = "blocked"
```

- [x] **Step 3: Implement `validate_signal_score_frame()`**

Required columns:

```python
SIGNAL_SCORE_COLUMNS = [
    "signal_time",
    "instrument_id",
    "score",
    "rank",
    "signal_state",
    "confidence",
    "horizon",
    "valid_until",
    "reason",
]
```

Validation behavior:

- required columns must exist.
- `signal_time` and `valid_until` convert with `pd.to_datetime`.
- `instrument_id` is stripped and uppercased.
- `score`, `rank`, and `confidence` are numeric.
- `confidence` must be between `0` and `1`.
- `signal_state` must match `SignalState` values.
- duplicate `signal_time + instrument_id` rows are rejected.
- result is sorted by `signal_time`, then `rank`, then `instrument_id`.

- [x] **Step 4: Implement `StrategyPlan`**

Use a dataclass with:

```python
plan_time: datetime
signals: pd.DataFrame
targets: pd.DataFrame
metadata: dict[str, Any] = field(default_factory=dict)
```

`__post_init__` must:

- validate `signals` with `validate_signal_score_frame`.
- validate `targets` with `validate_target_portfolio_frame`.
- preserve metadata as a copied dict.

- [x] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/strategy/test_strategy_contracts.py -v
```

Expected after implementation:

```text
4 passed
```

## Task 2: Add Signal Generator Protocol And Strategy Planner

**Files:**
- Create: `tests/strategy/test_strategy_planner.py`
- Create: `backtest/strategy/generator.py`
- Create: `backtest/strategy/planner.py`
- Modify: `backtest/strategy/__init__.py`

- [x] **Step 1: Write failing planner tests**

Create a simple test `SignalGenerator` that returns two signal rows:

```text
signal_time,instrument_id,score,rank,signal_state,confidence,horizon,valid_until,reason
2025-01-02 09:35:00,BTC/USDT,0.90,1,long_preferred,0.90,5m,2025-01-02 09:40:00,strong
2025-01-02 09:35:00,ETH/USDT,0.50,2,long_preferred,0.50,5m,2025-01-02 09:40:00,medium
```

Assert that `DefaultStrategyPlanner(generator, allocator).plan(context)` returns:

- a `StrategyPlan`.
- `signals` equal to the validated signal score frame.
- `targets` generated by `PortfolioAllocator`.
- metadata containing generator and allocator names when provided.

Also create a legacy Python strategy returning:


```text
date,symbol,target_weight
2025-01-02,BTC/USDT,0.30
2025-01-02,ETH/USDT,0.10
2025-01-03,BTC/USDT,0.00
```

Assert that `LegacyStrategyPlanner.from_python(...).plan(context)` returns:

- `targets` converted to `TargetPortfolioFrame`.
- `signals` derived from the legacy target weights.
- `rank` is per signal time and descending by score.
- positive weights map to `long_preferred`.
- zero weights map to `exit_preferred`.
- metadata contains `planner = "legacy"`.

Test command:

```bash
uv run pytest tests/strategy/test_strategy_planner.py -v
```

Expected before implementation:

```text
ModuleNotFoundError: No module named 'backtest.strategy.planner'
```

- [x] **Step 2: Implement `SignalGenerator` protocol**

Define:

```python
class SignalGenerator(Protocol):
    def generate(self, context: StrategyContext) -> pd.DataFrame:
        ...
```

The first phase uses existing `StrategyContext`; a future phase can introduce richer `StrategyPlanningContext`.

- [x] **Step 3: Implement `DefaultStrategyPlanner`**

Constructor:

```python
def __init__(
    self,
    generator: SignalGenerator,
    allocator: PortfolioAllocator,
    metadata: dict[str, Any] | None = None,
) -> None:
    ...
```

Behavior:

- call `generator.generate(context)`.
- validate the result as `SignalScoreFrame`.
- call `allocator.allocate(signals)`.
- return `StrategyPlan(plan_time=..., signals=signals, targets=targets, metadata=metadata)`.

- [x] **Step 4: Implement `LegacyStrategyPlanner`**

Factory methods:

```python
@classmethod
def from_python(cls, path: str | Path, function_name: str = "generate_signals") -> "LegacyStrategyPlanner"

@classmethod
def from_file(cls, path: str | Path) -> "LegacyStrategyPlanner"
```

Runtime behavior:

- Python provider calls existing `PythonSignalProvider`.
- File provider calls existing `FileSignalProvider`.
- The returned `SignalFrame` is converted with `legacy_signals_to_target_portfolio`.
- Signals are derived from targets:
  - `signal_time = timestamp`
  - `instrument_id = instrument_id`
  - `score = target_weight`
  - `rank = descending score within signal_time`
  - `signal_state = long_preferred` when `target_weight > 0`, otherwise `exit_preferred`
  - `confidence = target_weight clipped to [0, 1]`
  - `horizon = "legacy_signal"`
  - `valid_until = timestamp`
  - `reason = "legacy_target_weight"`
  - `StrategyPlan.metadata["planner"] = "legacy"`

- [x] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/strategy/test_strategy_planner.py -v
```

Expected after implementation:

```text
2 passed
```

## Task 3: Add Portfolio Allocator

**Files:**
- Create: `tests/portfolio/test_allocator.py`
- Create: `backtest/portfolio/allocator.py`
- Modify: `backtest/portfolio/__init__.py`

- [x] **Step 1: Write failing allocator tests**

Test cases:

- Top 2 equal allocation with `total_target_weight = 0.6` produces two `0.3` target weights.
- `min_score` filters weak long candidates.
- `exit_preferred` produces `target_weight = 0.0`.

Test command:

```bash
uv run pytest tests/portfolio/test_allocator.py -v
```

Expected before implementation:

```text
ModuleNotFoundError: No module named 'backtest.portfolio.allocator'
```

- [x] **Step 2: Implement `PortfolioAllocationConfig`**

Use a pydantic model:

```python
class PortfolioAllocationConfig(BaseModel):
    top_n: int | None = Field(default=None, gt=0)
    min_score: float | None = None
    total_target_weight: float = Field(default=1.0, ge=0, le=1)
    max_weight_per_instrument: float = Field(default=1.0, ge=0, le=1)
    weighting: Literal["equal", "score"] = "equal"
```

- [x] **Step 3: Implement `PortfolioAllocator.allocate()`**

Input:

```python
def allocate(self, signals: pd.DataFrame) -> pd.DataFrame:
```

Behavior:

- validate signals with `validate_signal_score_frame`.
- handle each `signal_time` independently.
- include `exit_preferred` rows as zero-weight targets.
- exclude `blocked` rows.
- for long candidates, filter by `min_score`.
- sort by `rank`, then descending `score`, then `instrument_id`.
- apply `top_n`.
- for `weighting = "equal"`, assign equal weights bounded by `max_weight_per_instrument`.
- for `weighting = "score"`, assign positive-score proportional weights bounded by `max_weight_per_instrument`.
- return `validate_target_portfolio_frame(...)`.

- [x] **Step 4: Export allocator classes**

Modify `backtest/portfolio/__init__.py` to export:

```python
PortfolioAllocationConfig
PortfolioAllocator
```

- [x] **Step 5: Run focused tests**

Run:

```bash
uv run pytest tests/portfolio/test_allocator.py -v
```

Expected after implementation:

```text
2 passed
```

## Task 4: Add Signal Evaluator

**Files:**
- Create: `tests/strategy/test_signal_evaluator.py`
- Create: `backtest/strategy/evaluation.py`
- Modify: `backtest/strategy/__init__.py`

- [x] **Step 1: Write failing evaluator tests**

Test a two-date, two-instrument example where score ranking perfectly matches future returns.

Assert:

- `signal_count = 4`
- `matched_count = 4`
- `top_n_mean_forward_return = 0.045`
- `all_mean_forward_return = 0.015`
- `rank_ic = 1.0`

Test command:

```bash
uv run pytest tests/strategy/test_signal_evaluator.py -v
```

Expected before implementation:

```text
ModuleNotFoundError: No module named 'backtest.strategy.evaluation'
```

- [x] **Step 2: Implement `SignalEvaluator`**

Public API:

```python
class SignalEvaluator:
    def __init__(self, top_n: int = 5) -> None:
        ...

    def evaluate(self, signals: pd.DataFrame, outcomes: pd.DataFrame) -> dict[str, float | int]:
        ...
```

`outcomes` required columns:

```text
signal_time
instrument_id
forward_return
```

Behavior:

- validate signals.
- normalize outcome timestamps and instrument ids.
- inner join signals to outcomes.
- compute mean return across all matched rows.
- compute Top-N mean return per signal time using rank ascending.
- compute average Spearman rank correlation between `score` and `forward_return` per signal time.
- return numeric dict.

- [x] **Step 3: Run focused tests**

Run:

```bash
uv run pytest tests/strategy/test_signal_evaluator.py -v
```

Expected after implementation:

```text
1 passed
```

## Task 5: Align Documentation

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/data-contracts.md`

- [x] **Step 1: Update architecture docs**

Document:

- legacy path remains `BacktestEngine -> SignalProvider -> BrokerEngine` for existing configs and regression checks.
- implemented target runtime path is `StrategyPlanner -> BacktestRunner -> ExecutionBackend`.
- new canonical path is component/data-product separated.
- `SignalGenerator` is a component.
- `SignalScoreFrame` and `TargetPortfolioFrame` are data products.
- first implementation phase does not replace `BacktestEngine`.

- [x] **Step 2: Update data contracts docs**

Add sections:

- `SignalScoreFrame`
- `TargetPortfolioFrame`
- `StrategyPlan`
- `PortfolioAllocator`
- legacy conversion from `SignalFrame` to `TargetPortfolioFrame` and derived signals.

- [x] **Step 3: Run doc-adjacent focused tests**

Run:

```bash
uv run pytest tests/strategy tests/portfolio/test_allocator.py -v
```

Expected:

```text
all selected tests pass
```

## Task 6: Regression Verification

**Files:**
- No additional files.

- [x] **Step 1: Run all new tests**

Run:

```bash
uv run pytest tests/strategy tests/portfolio/test_allocator.py -v
```

Expected:

```text
all selected tests pass
```

- [x] **Step 2: Run existing related tests**

Run:

```bash
uv run pytest tests/signals/test_signal_providers.py tests/core/test_targets.py tests/planning/test_order_planner.py tests/test_engine_e2e.py -v
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

- [x] **Step 4: Check changed files**

Run:

```bash
git status --short
git diff --stat
```

Expected:

```text
Only strategy architecture docs, new strategy modules, allocator module, and matching tests are changed.
```

## Review Gate

Review gate was satisfied before implementation. Keep this plan aligned with:

- `docs/superpowers/specs/2026-05-10-strategy-planning-architecture-design.md`
- `docs/superpowers/plans/2026-05-10-strategy-planning-architecture.md`
