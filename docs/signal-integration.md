# Signal Integration

Signals can come from CSV/Parquet files or from a Python strategy file. Both
paths must produce the same validated `SignalFrame`:

```text
date, symbol, target_weight
```

## File Signals

CSV and Parquet are supported by `FileSignalProvider`.

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

## Rules For Strategy Authors

- Return target portfolio weights, not orders.
- Keep total target weight per date at or below `1.0`.
- Use normalized symbols or values accepted by `normalize_symbol()`.
- Keep strategy code outside `backtest/`; load it through config.
- Do not bypass `validate_signal_frame()`.
