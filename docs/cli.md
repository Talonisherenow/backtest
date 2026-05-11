# CLI

The installed console script is `backtest`.

```bash
python -m pip install -e ".[dev]"
backtest --help
```

Examples use conventional paths such as `configs/demo.yaml` and
`signals/demo.csv`. Create those files first or replace the paths with files in
your workspace.

Current command groups:

```text
backtest run --config ...
backtest data ...
backtest chart ...
backtest validate ...
```

Do not use old plan text that says `backtest backtest run`.

## Run

Command shape for running a backtest from a YAML config:

```bash
backtest run --config configs/demo.yaml
```

Current implementation accepts the command shape, but cached-bar loading for
direct CLI runs is still a wiring point. Invoking the command directly exits
with a cached-bar loading message until that wiring is implemented; engine tests
currently run with an explicit `bars_override`.

## Data

Fetch the current all-board A-share universe:

```bash
backtest data universe --output data/universe/a_share_all.csv
```

Create a repeatable random stock batch from that universe:

```bash
backtest data sample-pool --universe data/universe/a_share_all.csv --size 200 --seed 42 --output data/universe/sample_200_seed_42.txt
```

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

## Chart

### Combined Workbench

Serve the Strategy Results viewer and the K-line viewer from one local process:

```bash
backtest chart serve-workbench \
  --results-root runs/ten_buy_signals/new_runtime_native_20260510 \
  --a-share-bars-root data/bars \
  --bitget-bars-root data/crypto/bitget/bars \
  --host 127.0.0.1 \
  --port 8767
```

Open:

```text
http://127.0.0.1:8767/
```

Routes:

- `/strategy-results` shows strategies and available backtest results.
- `/strategy-results/account?case_id=...` shows account-level equity, cash,
  return, holdings, and the full order list for a run.
- `/strategy-results/drilldown?case_id=...#symbol=...&order_id=...` shows a
  symbol-level K-line chart with executable buy/sell markers and symbol orders.
- `/kline` shows the cached K-line viewer across configured data sources.

This is the preferred interactive workflow. It reads result files and cached
bars on demand; no HTML generation step is required after running backtests.

### Dynamic Strategy Results

Serve only the dynamic Strategy Results viewer:

```bash
backtest chart serve-results \
  --results-root runs/ten_buy_signals/new_runtime_native_20260510 \
  --bars-root data/bars \
  --host 127.0.0.1 \
  --port 8766
```

Open:

```text
http://127.0.0.1:8766/strategy-results
```

### Dynamic K-line Viewer

Serve only the dynamic K-line viewer:

```bash
backtest chart serve \
  --a-share-bars-root data/bars \
  --bitget-bars-root data/crypto/bitget/bars \
  --host 127.0.0.1 \
  --port 8765
```

Open:

```text
http://127.0.0.1:8765/kline
```

The dynamic K-line viewer keeps the original bar-window interaction model:
symbol/source/frequency selection, search, older/newer/latest navigation,
jump-to-time, and slider position.

### Static K-line Snapshot

Build a reusable static K-line browser page from cached bars:

```bash
backtest chart viewer \
  --bars-root data/bars \
  --universe data/universe/board_sample_20_each_20260504_seed42_clean.csv \
  --symbols-file data/universe/board_sample_20_each_20260504_seed42_clean.txt \
  --output runs/charts/kline_viewer.html \
  --limit 300
```

The output HTML embeds the selected cached bars, so it can be opened directly
with `file://` and used to switch symbols, filter by board, search by code/name,
and change the visible range.

### Static Strategy Results Snapshot

Build a static Strategy Results catalog from one or more summary CSV files:

```bash
backtest chart strategy-results \
  --summary runs/ten_buy_signals/new_runtime_native_20260510/summary.csv \
  --output runs/charts/strategy_results_index.html
```

This command is useful for debugging or archived snapshots. The normal workflow
is `backtest chart serve-workbench`, which does not write HTML artifacts.

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

For larger batches, `stock_pool` can reference a generated symbol file instead:

```yaml
data:
  stock_pool:
    symbols_file: data/universe/sample_200_seed_42.txt
```

`report.html` is always written by the current `FileReportWriter`. The `html`
and `charts` flags are part of the config shape, but chart artifact generation
and disabling HTML output are not wired yet.
