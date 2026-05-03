# CLI

The installed console script is `backtest`.

```bash
python -m pip install -e ".[dev]"
backtest --help
```

Current command groups:

```text
backtest run --config ...
backtest data ...
backtest validate ...
```

Do not use old plan text that says `backtest backtest run`.

## Run

Run a backtest from a YAML config:

```bash
backtest run --config configs/demo.yaml
```

The command prints the created run directory on success. Current implementation
accepts the command shape, but cached-bar loading for direct CLI runs is still a
wiring point; engine tests currently run with an explicit `bars_override`.

## Data

Sync missing data:

```bash
backtest data sync --config configs/demo.yaml --metadata data/metadata.sqlite --bars-root data/bars
```

Show cached inventory:

```bash
backtest data inventory --metadata data/metadata.sqlite
```

Show missing ranges for a config:

```bash
backtest data coverage --config configs/demo.yaml --metadata data/metadata.sqlite
```

List crawl tasks:

```bash
backtest data tasks --metadata data/metadata.sqlite
```

Mark failed crawl tasks for retry:

```bash
backtest data retry --failed --metadata data/metadata.sqlite
```

`data sync` currently supports `source: akshare` only.

## Validate

Validate a config:

```bash
backtest validate config --config configs/demo.yaml
```

Validate a CSV or Parquet signal file:

```bash
backtest validate signals --path signals/demo.csv --symbol 000001.SZ
```

Repeat `--symbol` to provide the allowed stock pool. If omitted, the validator
uses symbols found in the signal file.

## Config Shape

Minimal YAML shape:

```yaml
project:
  name: demo
data:
  source: akshare
  frequency: 1d
  adjust: qfq
  start_date: 2025-01-01
  end_date: 2025-01-31
  stock_pool:
    symbols:
      - 000001.SZ
signals:
  type: file
  path: signals/demo.csv
execution:
  timing: next_open
  initial_cash: 1000000
  commission_rate: 0.0003
  min_commission: 5
  stamp_tax_rate: 0.0005
  transfer_fee_rate: 0.00001
  slippage_rate: 0.0005
  board_lot_size: 100
metrics:
  builtin:
    - total_return
report:
  output_dir: runs
  html: true
  charts: true
```
