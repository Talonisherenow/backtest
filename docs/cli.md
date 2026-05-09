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

Run a configured batch data sync job:

```bash
backtest data sync-job --job configs/data_jobs/crypto_bitget_core.yaml
```

The command prints a short summary and writes detailed artifacts:

```text
runs/crypto_market_data/bitget_core/summary.csv
runs/crypto_market_data/bitget_core/summary.json
```

If any item fails, the command exits with code `1` after writing the summary.
With `retry.continue_on_error: true`, remaining items still run before the final
non-zero exit.

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

`data sync` supports:

- `source: akshare` for A-share daily bars.
- `source: ccxt` for crypto spot historical OHLCV.

Crypto configs must set `data.exchange`; the catalog source becomes
`ccxt:<exchange>`.

## Chart

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
switch frequency, and move the visible window over the embedded bars.

For crypto cache inspection, omit `--frequency` so the viewer discovers all
cached timeframes under the root:

```bash
backtest chart viewer \
  --bars-root data/crypto/bitget/bars \
  --output runs/charts/crypto_kline_viewer.html \
  --limit 5000 \
  --adjust none
```

To inspect multiple cached sources in one HTML page, repeat `--source-root` with
`label=path` values:

```bash
backtest chart viewer \
  --source-root bitget=data/crypto/bitget/bars \
  --source-root binance=data/crypto/binance/bars \
  --output runs/charts/crypto_multi_source_viewer.html \
  --limit 5000 \
  --adjust none
```

The viewer shows the current source in the page header and summary. The Data
Status drawer contains the source switcher; after switching source, the main
symbol and frequency controls only show data from that source.

The viewer groups year-partitioned files for the same symbol/frequency into one
series. The top bar contains symbol, market/board, frequency, window size, and
position controls. The `Data Status` action is a separate title-area button that
opens a right drawer grouped by symbol and frequency.

`--limit` is the maximum embedded bars per symbol/frequency:

- `--limit 300` keeps the output small for daily A-share inspection.
- `--limit 5000` is useful for crypto intraday inspection while keeping the HTML
  reasonably responsive.
- `--limit 0` embeds all cached bars. This is the only way for a standalone
  HTML page to browse the full historical cache, but it can create a very large
  file.

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

Minimal crypto data sync shape:

```yaml
project:
  name: crypto-demo
data:
  source: ccxt
  exchange: binance
  frequency: 4h
  adjust: none
  start_date: 2025-01-01
  end_date: 2025-01-31
  stock_pool:
    symbols:
      - BTC/USDT
signals:
  type: file
  path: signals/demo.csv
execution:
  timing: next_open
  initial_cash: 100000
  commission_rate: 0.001
  min_commission: 0
  stamp_tax_rate: 0
  transfer_fee_rate: 0
  slippage_rate: 0.0005
  board_lot_size: 1
metrics:
  builtin:
    - total_return
report:
  output_dir: runs
  html: true
  charts: true
```

This fetches historical bars only. The current broker is still A-share oriented,
so a crypto data config should not be read as a complete crypto backtest or live
trading setup.

`report.html` is always written by the current `FileReportWriter`. The `html`
and `charts` flags are part of the config shape, but chart artifact generation
and disabling HTML output are not wired yet.
