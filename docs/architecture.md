# Architecture

## Purpose

This repo is an A-share backtesting MVP for local research. It is a Python
package plus CLI, not a multi-user service. The design goal is repeatable
backtests with explicit contracts between data, signals, execution, metrics, and
reports.

## Main Flow

```text
DataProvider -> DataSyncService -> ParquetBarStore
                         |              |
                         v              v
                  CrawlTaskManager   DataCatalog

Config -> BacktestEngine -> SignalProvider -> BrokerEngine -> Metrics -> Reports
```

## Package Boundaries

- `backtest.cli`: Typer commands. Current primary commands are `backtest run`,
  `backtest data ...`, and `backtest validate ...`.
- `backtest.config`: Pydantic config models and YAML loading.
- `backtest.core`: shared enums, symbols, frame validators, and contract models.
- `backtest.data`: providers, Parquet store, SQLite metadata, catalog, crawl
  tasks, and sync service.
- `backtest.signals`: file and Python signal providers plus validation.
- `backtest.broker`: execution loop, account state, costs, slippage, and result
  frames.
- `backtest.metrics`: built-in metric functions, custom metric registry, and
  result context.
- `backtest.reports`: manifest building, structured file output, and HTML report
  rendering.

## Important Boundaries

- Data source logic belongs in `DataProvider` implementations, not in broker,
  metrics, or reports.
- Cached data should be discovered through `DataCatalog` and read through
  `ParquetBarStore`, not inferred from raw folder names by callers.
- Strategy code stays outside the core engine. The engine accepts signals through
  `FileSignalProvider` or `PythonSignalProvider` and validates them into the
  same `SignalFrame` shape.
- Validation layers are intentional. Configs, bar frames, signal frames, and
  report run IDs all validate inputs before downstream use.
- Reports are both human-readable and machine-readable. Future GUI tools should
  consume JSON and Parquet artifacts rather than scraping `report.html`.

## Universal Trading Evolution

The next architecture separates strategy decisions from execution facts:

```text
MarketDataProvider
  -> StrategyRunner
  -> TargetPortfolio / OrderIntent
  -> RiskGate
  -> OrderLedger
  -> ExecutionAdapter
  -> ExecutionReport
  -> PortfolioState
```

Backtests and live trading should share strategy, target, order intent, risk,
and portfolio contracts. They should not share execution implementation:
backtests use a simulation adapter, while live trading uses broker or exchange
API adapters.

## Current MVP Limitations

- `AkShareProvider` supports daily bars only.
- `CCXTOHLCVProvider` supports crypto spot historical OHLCV only; it is not a
  live trading adapter.
- `BrokerEngine` supports `next_open` execution only.
- The run CLI is present as `backtest run --config ...`; current engine tests
  use `bars_override`, and direct cached-bar loading for CLI execution is still a
  wiring point.
