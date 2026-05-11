# Data Contracts

## Symbols

Use normalized A-share symbols in the form `000001.SZ`, `600519.SH`, or
`430017.BJ`. `normalize_symbol()` also accepts six-digit symbols and
`SZ000001`/`SH600519`/`BJ430017` style input, then converts them to the
normalized form.

Bare six-digit symbols are inferred by exchange prefix:

- `4` and `8` prefixes become `.BJ`.
- `5`, `6`, and `9` prefixes become `.SH`.
- Other prefixes become `.SZ`.

## Stock Pool

Backtest configs can provide a stock pool inline:

```yaml
stock_pool:
  symbols:
    - 000001.SZ
    - 600519.SH
```

They can also point to a text or CSV symbol file:

```yaml
stock_pool:
  symbols_file: data/universe/sample_200_seed_42.txt
```

Text files use one symbol per line. CSV files must contain a `symbol` column.
Relative `symbols_file` paths are resolved from the config file directory.

## BarFrame

Required columns:

```text
date
symbol
open
high
low
close
volume
amount
frequency
adjust
```

Allowed `frequency` values:

```text
1d, 1m, 5m, 15m, 30m, 60m
```

Allowed `adjust` values:

```text
none, qfq, hfq
```

Validation performed by `validate_bar_frame()`:

- Required columns must exist.
- Dates are converted with `pandas.to_datetime`.
- Symbols are normalized.
- Frequency and adjust values must match enums.
- OHLC, volume, and amount must be numeric and non-null.
- Prices cannot be negative.
- `high >= low`.
- `open` and `close` must be inside `[low, high]`.
- Output is sorted by `symbol, date`.

Optional execution columns may be present and are used by the broker when
available:

```text
is_suspended
limit_up
limit_down
```

## SignalFrame

Required columns:

```text
date
symbol
target_weight
```

Validation performed by `validate_signal_frame()`:

- Required columns must exist.
- Dates are converted with `pandas.to_datetime`.
- Symbols are normalized.
- `target_weight` must be numeric, non-null, and between `0` and `1`.
- No duplicate `date + symbol` rows.
- Sum of `target_weight` per date must not exceed `1.0`.
- If a stock pool is provided, every signal symbol must be in it.
- Output is sorted by `date, symbol`.

`SignalFrame` is the legacy signal-provider contract. It already contains
target weights, so it mixes signal generation and allocation. New strategy work
should prefer `SignalScoreFrame -> PortfolioAllocator -> TargetPortfolioFrame`.

## SignalScoreFrame

Required columns:

```text
signal_time
instrument_id
score
rank
signal_state
confidence
horizon
valid_until
reason
```

Validation performed by `validate_signal_score_frame()`:

- Required columns must exist.
- `signal_time` and `valid_until` are converted with `pandas.to_datetime`.
- `instrument_id` is stripped and uppercased.
- `score`, `rank`, and `confidence` must be numeric.
- `confidence` must be between `0` and `1`.
- `signal_state` must be one of `long_preferred`, `neutral`,
  `exit_preferred`, or `blocked`.
- No duplicate `signal_time + instrument_id` rows.
- Output is sorted by `signal_time, rank, instrument_id`.

`SignalScoreFrame` expresses strategy judgment. It is not a target portfolio and
it is not an order. Avoid `buy`, `sell`, and `hold` as signal states because
actual order direction is calculated later from target weight versus current
portfolio weight.

## Instrument

`Instrument` is the market-neutral identifier for a tradable or researchable
asset. It replaces assumptions that every asset is an A-share stock.

Required fields:

```text
instrument_id
market
exchange
asset_class
quote_currency
```

Examples:

```text
000001.SZ
00700.HK
AAPL.US
BTC-USDT.BINANCE
```

## TargetPortfolioFrame

Required columns:

```text
timestamp
instrument_id
target_weight
```

This frame expresses desired portfolio exposure. It is not an order and does
not imply that a broker accepted or filled anything.

`PortfolioAllocator` converts `SignalScoreFrame` into `TargetPortfolioFrame`.
The first implementation supports Top-N selection, equal weighting, score
weighting, score thresholds, max single-instrument weight, total target weight,
zero targets for `exit_preferred`, and exclusion of `blocked` signals.

## StrategyPlan

`StrategyPlan` is the output of `StrategyPlanner`, the strategy-stage
orchestrator.

Required fields:

```text
plan_time
signals
targets
metadata
```

`signals` must be a valid `SignalScoreFrame`. `targets` must be a valid
`TargetPortfolioFrame`. `StrategyPlan` does not contain `OrderIntent`; order
creation belongs to `OrderPlanner`.

## BacktestExecutionResult

`BacktestExecutionResult` is the normalized output of an execution backend.
Both legacy and native backtest backends must return this shape.

Required fields:

```text
equity_curve
positions
orders
trades
metadata
```

The first runtime implementation keeps the same DataFrame columns as the
existing `BrokerResult`, so metrics and reports can be reused while the native
execution path is introduced.

## BacktestRunResult

`BacktestRunResult` is the output of `BacktestRunner`.

Required fields:

```text
plans
signals
targets
execution
metadata
```

`plans` contains the collected `StrategyPlan` objects. `signals` is the merged
`SignalScoreFrame`, `targets` is the merged `TargetPortfolioFrame`, and
`execution` is a `BacktestExecutionResult` produced by the selected
`ExecutionBackend`.

## Runtime Backend Parity

`LegacyBrokerExecutionBackend` converts `TargetPortfolioFrame` into the legacy
`SignalFrame` contract:

```text
timestamp      -> date
instrument_id  -> symbol
target_weight  -> target_weight
```

`NativeSimulationBackend` must match the legacy backend for the current A-share
MVP semantics: `next_open`, sell-before-buy rebalances, board lots, fees,
slippage, suspended bars, limit up/down, missing execution bars, cash limits,
and equity curve marking. Parity tests are the migration guardrail.

## OrderIntent

`OrderIntent` is the internal order command created after target weights are
known. In the current strategy-planning path, it is created by `OrderPlanner`,
not by `SignalGenerator` or `PortfolioAllocator`.

Required fields:

```text
account_id
client_order_id
strategy_id
instrument_id
side
quantity
order_type
time_in_force
created_at
```

`OrderIntent` is not an execution result. The system updates portfolio state
from `ExecutionReport`, not from the intent.

## OrderLedger

`OrderLedger` records order intent and execution report state. The phase-1
implementation stores rows in SQLite and scopes them by `account_id`.

Every order, execution report, portfolio state, and ledger row is account-scoped.
Phase 1 uses `account_id=default` unless a caller passes a different account.

## Converting Existing Data

For existing market data, rename source columns into the `BarFrame` names above,
add `frequency` and `adjust`, normalize symbols, then run
`validate_bar_frame()` before writing with `ParquetBarStore`.

For existing signals or model outputs, convert them to target portfolio weights.
The engine does not accept side/quantity/order intent as its public signal
contract; it accepts desired `target_weight` by date and symbol.

Example signal file:

```csv
date,symbol,target_weight
2025-01-02,000001.SZ,0.20
2025-01-02,600519.SH,0.30
```

Legacy `SignalFrame` data can enter the new strategy-planning path through
`LegacyStrategyPlanner`. It converts `date/symbol/target_weight` into
`timestamp/instrument_id/target_weight`, and derives a minimal
`SignalScoreFrame` where `score = target_weight`, positive weights become
`long_preferred`, and zero weights become `exit_preferred`.
