# Signal Integration

This document describes the legacy signal-provider path used by
`BacktestEngine`. Signals can come from CSV/Parquet files or from a Python
strategy file. Both paths must produce the same validated `SignalFrame`:

```text
date, symbol, target_weight
```

## File Signals

CSV and Parquet are supported by `FileSignalProvider`.
Create the file first or replace `signals/demo.csv` with your own path.

Config:

```yaml
signals:
  type: file
  path: signals/demo.csv
```

Validate before running:

```bash
backtest validate signals --path signals/demo.csv --symbol 000001.SZ --symbol 600519.SH
```

If `--symbol` is omitted, the validator reads symbols from the file and uses
them as the allowed pool. During a backtest, the config stock pool is the allowed
pool.

## Python Signals

Python strategies are loaded from a file path and function name. The default
function name is `generate_signals`.

Config:

```yaml
signals:
  type: python
  path: strategies/my_strategy.py
  function: generate_signals
```

Strategy file:

```python
import pandas as pd


def generate_signals(context):
    bars = context.bars
    stock_pool = context.stock_pool

    return pd.DataFrame(
        {
            "date": [context.start_date],
            "symbol": [stock_pool[0]],
            "target_weight": [0.20],
        }
    )
```

`StrategyContext` provides:

```text
bars
stock_pool
start_date
end_date
params
```

`start_date` and `end_date` are ISO strings. `bars` is a validated `BarFrame`.

## New Strategy Planning Path

New strategy work should prefer the strategy-planning contracts:

```text
SignalGenerator -> SignalScoreFrame
PortfolioAllocator -> TargetPortfolioFrame
StrategyPlanner -> StrategyPlan
BacktestRunner -> ExecutionBackend
```

Legacy `SignalFrame` data can still enter that path through
`LegacyStrategyPlanner`, which converts target weights to
`TargetPortfolioFrame` and derives a minimal `SignalScoreFrame`. That adapter is
for compatibility; it does not turn legacy signal providers into full
signal-scoring implementations.

## Rules For Strategy Authors

- In the legacy provider path, return target portfolio weights, not orders.
- In the new planning path, implement `SignalGenerator` for scores/ranks/states
  and let `PortfolioAllocator` produce target weights.
- Keep total target weight per date at or below `1.0`.
- Use normalized symbols or values accepted by `normalize_symbol()`.
- Keep strategy code outside `backtest/`; load it through config.
- Do not bypass `validate_signal_frame()`.
