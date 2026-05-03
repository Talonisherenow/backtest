# Reports

Backtest outputs are written by `FileReportWriter` under:

```text
<report.output_dir>/<safe_run_id>/
```

`safe_run_id` is generated from the project name plus a UTC timestamp. Report
writing rejects path traversal run IDs.

## Emitted Files

```text
manifest.json
metrics.json
equity_curve.parquet
positions.parquet
orders.parquet
trades.parquet
report.html
```

## Manifest

`manifest.json` contains run metadata:

```text
run_id
project_name
created_at
config_path
config_hash
signal_source
data_source
symbols
start_date
end_date
benchmark
engine_version
```

Use it to identify a run, trace the source config, compare config hashes, and
display basic run metadata.

## Metrics

`metrics.json` contains built-in metric values and serialized custom
`MetricResult` payloads. GUI tools should prefer this file for summary cards,
tables, and metric panels.

## Structured Frames

Parquet outputs are the canonical data source for charts and drilldowns:

- `equity_curve.parquet`: `date`, `equity`, `cash`.
- `positions.parquet`: `date`, `symbol`, `shares`.
- `orders.parquet`: `date`, `symbol`, `side`, `requested_shares`,
  `filled_shares`, `price`, `commission`, `tax`, `transfer_fee`,
  `slippage_cost`, `status`, `reason`.
- `trades.parquet`: `date`, `symbol`, `side`, `shares`, `price`.

## HTML Report

`report.html` is a lightweight human-readable report. Future GUI or notebook
tools should not scrape it. Consume `manifest.json`, `metrics.json`, and Parquet
files instead.

The current `FileReportWriter` always writes `report.html`. Config flags such as
`report.html` and `report.charts` are present in the config model, but disabling
HTML output and emitting chart artifacts are not wired yet.
