# Data Contracts

## Symbols

Use normalized A-share symbols in the form `000001.SZ` or `600519.SH`.
`normalize_symbol()` also accepts six-digit symbols and `SZ000001`/`SH600519`
style input, then converts them to the normalized form.

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
