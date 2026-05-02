# A Share Backtest System Design

Date: 2026-05-03
Status: Draft for user review
Workspace: `/Users/talon/code/backtest`

## 1. Purpose

Build a local, research-first A share backtesting system as a Python package plus CLI. The MVP should let a user:

- Fetch and cache A share OHLCV market data.
- Track what data has already been fetched and which crawl tasks succeeded or failed.
- Provide trading signals from either Python strategy code or CSV/Parquet files.
- Execute signals under configurable A share trading assumptions.
- Evaluate strategy performance with built-in and custom metrics.
- Export structured results and visual reports.
- Leave clear extension points so future data sources, signal formats, execution models, metrics, and GUI layers can be added without rewriting the core engine.

The system is intentionally not a multi-user platform in the first version. It should be a sharp local research tool with clean boundaries.

## 2. Scope

### MVP Includes

- Python package and CLI.
- Daily bars as the first supported frequency.
- Frequency-aware interfaces so minute bars can be added later.
- Pluggable data provider interface.
- Default AkShare data provider.
- Parquet market data cache.
- SQLite metadata database for catalog and crawl task state.
- User-defined stock pools.
- Front-adjusted, back-adjusted, and unadjusted price mode in the data contract, with front-adjusted data as the recommended default for research.
- Signal ingestion from Python strategy functions.
- Signal ingestion from CSV/Parquet files.
- Unified internal `SignalFrame` format.
- Configurable execution timing, defaulting to signal date plus next trading day open.
- Basic A share execution constraints.
- Built-in core performance metrics.
- Custom metric registration.
- Structured output files plus HTML/chart report.
- Durable documentation for future users and future model sessions.

### MVP Does Not Include

- Full A share universe as the default operating mode.
- Fully interactive GUI.
- Production task queue or distributed crawler.
- Tick-level or intraday matching engine.
- Volume participation, market impact, or partial-fill simulation.
- Portfolio optimization engine.
- Live trading.

These are future extensions, not first-version requirements.

## 3. Confirmed Design Decisions

- Product shape: Python package plus CLI.
- Primary use case: local quantitative research and repeatable strategy backtests.
- Data frequency: daily first, with frequency-aware design for future minute bars.
- Data source design: pluggable data sources, default implementation via AkShare.
- Storage: Parquet for market data, SQLite for metadata and crawl tasks.
- Signal input: both Python strategy functions and CSV/Parquet signal files.
- Internal signal format: unified `SignalFrame`.
- Execution timing: configurable, default signal date plus next trading day open.
- Trading constraints: A share basic constraints, including T+1, board lot sizing, fees, stamp tax, slippage, suspension, and limit-up/limit-down handling.
- Stock range: custom stock pool in MVP.
- Performance output: core metrics plus visual report.
- Custom evaluation: metric registry and custom metric interface.
- GUI: not in MVP, but report and metric outputs must be embeddable by future GUI frameworks.

## 4. Architecture

The core flow is:

```text
DataProvider -> CrawlTaskManager -> BarStore -> SignalProvider -> Broker -> Metrics -> Reports
                                      |
                                      v
                                  DataCatalog
```

Proposed package layout:

```text
backtest/
  data/        Data providers, data catalog, crawl tasks, Parquet bar store
  signals/     Python/file signal providers, SignalFrame validation
  broker/      Execution model, account, positions, orders, A share constraints
  metrics/     Built-in metrics, custom metric registry
  reports/     Structured exports, charts, HTML reports
  cli/         Command line entrypoints
  config/      YAML config schema and validation
```

The MVP should stay modular. Each module should expose stable contracts and hide implementation details.

## 5. Extension Points

### DataProvider

Provides market data from an external source.

First implementation:

- `AkShareProvider`

Future implementations:

- `TushareProvider`
- `LocalFileProvider`
- Vendor-specific provider

Expected interface:

```python
class DataProvider:
    def fetch_bars(self, request: BarRequest) -> BarFrame:
        ...
```

### BarStore

Reads and writes cached market data.

First implementation:

- `ParquetBarStore`

Future implementations:

- DuckDB-backed query layer
- Database-backed store
- Remote object storage store

### SignalProvider

Loads or generates trading signals.

First implementations:

- `PythonSignalProvider`
- `FileSignalProvider`

Future implementations:

- Notebook/export adapter
- Factor model adapter
- ML model adapter

### ExecutionModel

Converts normalized signals into orders and fills.

Default:

- Signal generated on day T.
- Execute at next trading day open.

Future implementations:

- Same-day close execution.
- Next-day close execution.
- Minute-bar execution.
- Volume-aware execution.

### CostModel and SlippageModel

Keep fee, tax, and slippage logic separate from order generation.

This avoids hard-coding market assumptions into the broker loop.

### Metric and MetricRegistry

Allows custom strategy evaluation without modifying core performance code.

Metric results can be:

- `scalar`: one number, such as Sharpe ratio.
- `series`: time series, such as rolling return.
- `table`: tabular output, such as trade-level diagnostics.

### ReportWriter

Allows reports to be written to different destinations.

First implementations:

- `FileReportWriter`
- `HtmlReportWriter`

Future implementations:

- Streamlit app
- Dash/Plotly app
- Panel app
- Web API response
- Database sink

## 6. Data Design

### BarFrame

The internal market data format should include these required fields:

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

Optional fields:

```text
pre_close
pct_change
turnover
is_suspended
limit_up
limit_down
source
updated_at
```

### Symbol Format

Use normalized A share symbols:

```text
000001.SZ
600519.SH
```

Adapters may accept source-specific formats, but they must normalize before returning data to the rest of the system.

### Frequency

The MVP supports `1d`.

The schema and interfaces should reserve the ability to support:

```text
1m
5m
15m
30m
60m
```

### Adjust Mode

Supported values:

```text
none
qfq
hfq
```

Recommended MVP default:

```text
qfq
```

### Parquet Cache Layout

Recommended layout:

```text
data/
  bars/
    frequency=1d/
      adjust=qfq/
        symbol=000001.SZ/
          year=2024/
            bars.parquet
```

This keeps large time-series data efficient while preserving future partitioning by frequency, adjust mode, symbol, and year.

## 7. Data Catalog and Crawl Task Management

The system needs first-class metadata. It should not rely only on scanning files.

### Metadata Store

Use SQLite:

```text
data/
  metadata.sqlite
```

This database stores catalog records and crawl task lifecycle state.

### DataCatalog

Tracks which local data exists and its coverage.

Representative fields:

```text
symbol
frequency
adjust
start_date
end_date
rows
source
cache_path
updated_at
quality_status
```

Questions it must answer:

- Which symbols are cached locally?
- Which date range is covered for each symbol, frequency, and adjust mode?
- Which requested symbols have missing ranges?
- Which cache files correspond to a symbol?
- When was a symbol last updated?

### CrawlTaskManager

Tracks data fetch jobs and retry state.

Representative task fields:

```text
task_id
symbol
frequency
adjust
start_date
end_date
source
status
attempts
last_error
created_at
updated_at
started_at
finished_at
```

Task statuses:

```text
pending
running
success
failed
cancelled
retrying
```

This manager supports progress visibility and failed-task retry.

### Data CLI Commands

The design should support:

```bash
backtest data sync --config configs/demo.yaml
backtest data inventory
backtest data coverage --config configs/demo.yaml
backtest data tasks
backtest data retry --failed
```

## 8. Signal Design

### SignalFrame

All signal inputs become a normalized `SignalFrame`.

Required fields:

```text
date
symbol
target_weight
```

Optional fields:

```text
signal_time
rebalance_group
priority
reason
```

`target_weight` means the desired portfolio weight for the symbol at the configured execution time.

MVP constraints:

- No short selling.
- `target_weight` must be between `0` and `1`.
- Total target weight for one signal date must not exceed `1`.
- Symbols must be in the configured stock pool unless explicitly allowed.
- Duplicate `date + symbol` signals are invalid unless a documented aggregation rule is configured.

### Python Strategy Input

Expected shape:

```python
def generate_signals(context) -> pandas.DataFrame:
    ...
```

The strategy context should provide access to:

- Bar data.
- Stock pool.
- Date range.
- Current config.
- Optional user parameters.

### File Signal Input

CSV and Parquet files must match the `SignalFrame` schema.

Example:

```text
date,symbol,target_weight
2025-01-02,000001.SZ,0.10
2025-01-02,600519.SH,0.20
2025-01-03,000001.SZ,0.00
```

The file provider is the main bridge for existing models or external signal pipelines.

## 9. Execution Design

The broker converts target weights into executable orders and fills.

Default flow:

```text
Read signal for date T
Find execution date and execution price
Calculate target market value
Compare with current holdings
Generate buy/sell orders
Apply constraints, cost model, and slippage model
Update cash, positions, orders, trades, and daily equity
```

### Default Execution Timing

```text
signal date T -> next trading day open
```

This avoids accidental future-looking use of same-day close prices.

### A Share Constraints

MVP constraints:

- T+1 sell restriction.
- Buy orders rounded to 100-share board lots.
- Cash cannot go negative.
- Cannot sell more than available shares.
- Commission.
- Minimum commission.
- Sell-side stamp tax.
- Slippage.
- Suspended stocks cannot trade.
- Limit-up stocks cannot be bought by default.
- Limit-down stocks cannot be sold by default.

### Order and Trade Records

Orders should preserve rejected or adjusted intent.

Representative order fields:

```text
date
symbol
side
requested_shares
filled_shares
price
commission
tax
slippage_cost
status
reason
```

Rejected or adjusted orders should be visible in reports.

## 10. Metrics and Evaluation Design

The metrics module computes performance from:

- Equity curve.
- Daily returns.
- Positions.
- Trades.
- Orders.
- Market data.
- Config.

### Built-in Metrics

MVP built-ins:

```text
total_return
annualized_return
annualized_volatility
max_drawdown
sharpe_ratio
win_rate
profit_loss_ratio
turnover
trade_count
avg_holding_days
cash_ratio
```

Optional benchmark metrics if a benchmark is configured:

```text
benchmark_return
excess_return
tracking_difference
```

### Custom Metrics

Custom metrics should implement a stable interface:

```python
class Metric:
    name: str

    def calculate(self, context: BacktestResultContext) -> MetricResult:
        ...
```

Example config shape:

```yaml
metrics:
  builtin:
    - total_return
    - max_drawdown
    - sharpe_ratio
  custom:
    - path: strategies/metrics.py
      class: MyCustomMetric
```

This supports future evaluation ideas such as signal-forward returns, trade-level diagnostics, rolling risk metrics, or custom scoring systems without changing the core engine.

## 11. Reports and GUI Readiness

The MVP does not include an interactive GUI, but it must export results in a GUI-friendly way.

Each run should write:

```text
runs/
  20260503_153000_my_strategy/
    config.yaml
    manifest.json
    metrics.json
    custom_metrics/
    equity_curve.parquet
    positions.parquet
    trades.parquet
    orders.parquet
    report.html
    charts/
      equity_curve.png
      drawdown.png
      monthly_returns.png
```

The HTML report should include:

- Strategy and run metadata.
- Core metric cards.
- Equity curve.
- Drawdown chart.
- Monthly return chart.
- Trade summary.
- Rejected or adjusted order summary.
- Custom metric outputs where possible.

Future GUI options can read these structured files directly:

- Streamlit.
- Dash and Plotly.
- Panel.
- Custom web frontend.

The first version should avoid coupling the engine to any one GUI framework.

## 12. Run Manifest

Each backtest run should include a `manifest.json` for reproducibility.

Representative fields:

```text
run_id
created_at
config_path
config_hash
strategy_path
strategy_hash
signal_source
data_source
data_frequency
adjust
symbols
start_date
end_date
benchmark
engine_version
```

This lets future users and model sessions understand exactly how a result was produced.

## 13. Config Design

Use YAML as the primary configuration format.

Representative config:

```yaml
project:
  name: demo_strategy

data:
  source: akshare
  frequency: 1d
  adjust: qfq
  start_date: "2020-01-01"
  end_date: "2025-12-31"
  stock_pool:
    symbols:
      - 000001.SZ
      - 600519.SH

signals:
  type: file
  path: signals/demo_signals.parquet

execution:
  timing: next_open
  initial_cash: 1000000
  commission_rate: 0.0003
  min_commission: 5
  stamp_tax_rate: 0.0005
  slippage_rate: 0.0005
  board_lot_size: 100

metrics:
  builtin:
    - total_return
    - annualized_return
    - max_drawdown
    - sharpe_ratio

report:
  output_dir: runs
  html: true
  charts: true
```

The config loader should validate field types, date formats, enum values, and required sections before starting a crawl or backtest.

## 14. CLI Design

Data commands:

```bash
backtest data sync --config configs/demo.yaml
backtest data inventory
backtest data coverage --config configs/demo.yaml
backtest data tasks
backtest data retry --failed
```

Backtest commands:

```bash
backtest run --config configs/demo.yaml
backtest report --run runs/20260503_153000_demo_strategy
```

Utility commands:

```bash
backtest validate config --config configs/demo.yaml
backtest validate signals --path signals/demo_signals.parquet
```

The CLI should be human-readable by default and allow machine-readable output later with a `--json` option.

## 15. Documentation Deliverables

The MVP should include durable docs so future model sessions and human users can quickly understand and operate the framework.

### README.md

Purpose:

- Explain what the project does.
- Show installation/setup.
- Provide a minimal end-to-end example.
- Link to deeper docs.

### docs/architecture.md

Purpose:

- Explain module boundaries.
- Show data flow.
- Name extension points.
- Tell future model sessions where to make changes.

### docs/data-ingestion.md

Purpose:

- Explain how to fetch data.
- Explain the data catalog.
- Explain crawl tasks, status, retries, and coverage checks.
- Show common data CLI workflows.

### docs/data-contracts.md

Purpose:

- Define `BarFrame`.
- Define `SignalFrame`.
- Define orders, trades, positions, equity curve, metric result, and run manifest schemas.
- Explain how existing CSV/Parquet data should be converted into system-recognized formats.

### docs/signal-integration.md

Purpose:

- Show how to write Python strategy functions.
- Show how to prepare CSV/Parquet signal files.
- Explain validation errors and how to fix them.
- Explain how external models should export signals.

### docs/metrics-extension.md

Purpose:

- Explain built-in metrics.
- Explain the custom metric interface.
- Show how to register custom metrics in config.
- Explain `scalar`, `series`, and `table` metric results.

### docs/reports.md

Purpose:

- Explain output files.
- Explain HTML report contents.
- Explain which files future GUI tools should consume.

### docs/cli.md

Purpose:

- List commands and examples.
- Explain expected inputs and outputs.
- Include troubleshooting tips.

### docs/ai-handoff.md

Purpose:

- Provide a short guide for future model sessions.
- State which docs to read first.
- Summarize key contracts and invariants.
- Warn against bypassing `SignalFrame`, `DataCatalog`, or config validation.

Recommended reading order for future model sessions:

```text
README.md
docs/architecture.md
docs/data-contracts.md
docs/ai-handoff.md
```

## 16. Error Handling

Expected error categories:

- Invalid config.
- Data provider failure.
- Missing data coverage.
- Cache read/write failure.
- Catalog/task metadata failure.
- Signal schema validation failure.
- Signal target weight violation.
- Execution rejection due to constraints.
- Report generation failure.

Data crawl failures should be recorded in the task table and retried by explicit command.

Execution rejections should not crash the backtest. They should be written to the orders output with a clear reason.

Configuration and signal schema errors should fail fast before running expensive work.

## 17. Testing Strategy

The MVP should include tests for:

- Config validation.
- Symbol normalization.
- BarFrame schema validation.
- Parquet cache read/write.
- DataCatalog coverage detection.
- CrawlTaskManager lifecycle and retry selection.
- SignalFrame validation.
- File signal ingestion.
- Python signal ingestion.
- Target weights to orders.
- T+1 sell restriction.
- Board lot rounding.
- Commission, minimum commission, stamp tax, and slippage.
- Suspension and limit-up/limit-down rejection.
- Equity curve generation.
- Built-in metrics.
- Custom metric registration.
- End-to-end backtest on a small fixture dataset.

Tests should use small deterministic fixture data rather than live AkShare calls where possible.

## 18. Risks and Mitigations

### Data Source Instability

AkShare can change behavior because it often depends on upstream data endpoints.

Mitigation:

- Keep `DataProvider` isolated.
- Cache fetched data.
- Record source and update time.
- Prefer deterministic tests with fixtures.

### Future-Looking Bias

Same-day signal and same-day close execution can accidentally introduce lookahead bias.

Mitigation:

- Default to next trading day open.
- Make execution timing explicit in config and manifest.

### Overbuilt Plugin System

Too much abstraction can slow down MVP delivery.

Mitigation:

- Use simple interfaces.
- Implement only one default provider/store/report writer first.
- Add extension points where volatility is likely, not everywhere.

### Metadata Drift

Catalog data can become inconsistent with Parquet files.

Mitigation:

- Write cache and catalog updates in a controlled sequence.
- Provide a future reconciliation command.
- Store row counts and cache paths.

## 19. MVP Implementation Defaults

Use these defaults unless implementation discovers a concrete blocker:

- Use pandas as the primary internal table engine because it is the most familiar choice for local quant research and integrates cleanly with CSV/Parquet workflows.
- Use Typer for the CLI because it gives readable commands, typed parameters, and useful help output with little boilerplate.
- Use Pydantic for config and schema validation so errors are explicit before data crawls or backtests start.
- Use Plotly for first-version HTML charts because future GUI layers can reuse the same interactive chart model.
- Use optional static PNG export only when the required image export dependency is available.
- Verify the current AkShare daily A share endpoint behavior during implementation before locking the adapter, because upstream data APIs can change.

## 20. Approval Criteria

The design is ready for implementation planning when the user confirms:

- The module boundaries are correct.
- The data catalog and crawl task manager are part of MVP.
- The documentation deliverables are useful and sufficient for future operation.
- GUI is deferred, but outputs remain GUI-ready.
- The first version can prioritize correctness and clarity over platform complexity.
