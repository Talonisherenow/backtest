# Architecture

## Purpose

This repo is an A-share backtesting MVP for local research. It is a Python
package plus CLI, not a multi-user service. The design goal is repeatable
backtests with explicit contracts between data, signals, execution, metrics, and
reports.

## Target Runtime Flow

The new canonical runtime flow is:

```text
DataProvider -> DataSyncService -> ParquetBarStore
                         |              |
                         v              v
                  CrawlTaskManager   DataCatalog

StrategyPlanner
  -> SignalGenerator
  -> PortfolioAllocator
  -> StrategyPlan
       -> TargetPortfolioFrame

BacktestRunner
  -> ExecutionBackend
       -> NativeSimulationBackend
       -> LegacyBrokerExecutionBackend
  -> BacktestRunResult
       -> Metrics
       -> Reports
```

`NativeSimulationBackend` is the target backtest execution path.
`LegacyBrokerExecutionBackend` exists so the new runtime can be checked against
the current `BrokerEngine` behavior while migration is still in progress.

## Current Legacy Flow

```text
DataProvider -> DataSyncService -> ParquetBarStore
                         |              |
                         v              v
                  CrawlTaskManager   DataCatalog

Config -> BacktestEngine -> SignalProvider -> BrokerEngine -> Metrics -> Reports
```

The legacy flow remains available for existing configs and regression checks. It
is not the target architecture for new strategy work.

## Package Boundaries

- `backtest.cli`: Typer commands. Current primary commands are `backtest run`,
  `backtest data ...`, and `backtest validate ...`.
- `backtest.config`: Pydantic config models and YAML loading.
- `backtest.core`: shared enums, symbols, frame validators, and contract models.
- `backtest.data`: providers, Parquet store, SQLite metadata, catalog, crawl
  tasks, and sync service.
- `backtest.signals`: file and Python signal providers plus validation.
- `backtest.strategy`: signal score contracts, strategy planning, legacy signal
  provider adapters, and pre-execution signal evaluation.
- `backtest.portfolio`: portfolio state and target allocation from signal
  scores.
- `backtest.runtime`: new-architecture backtest runner, runtime result
  contracts, and execution backends.
- `backtest.broker`: execution loop, account state, costs, slippage, and result
  frames. In the new architecture this is wrapped as a compatibility backend.
- `backtest.metrics`: built-in metric functions, custom metric registry, and
  result context.
- `backtest.reports`: manifest building, structured file output, and HTML report
  rendering.
- `backtest.charts`: local chart/viewer surfaces, including dynamic K-line,
  Strategy Results, account viewer, order drilldown, and the combined workbench
  server.

## Important Boundaries

- Data source logic belongs in `DataProvider` implementations, not in broker,
  metrics, or reports.
- Cached data should be discovered through `DataCatalog` and read through
  `ParquetBarStore`, not inferred from raw folder names by callers.
- Strategy code stays outside the core engine. The legacy engine accepts
  `FileSignalProvider` or `PythonSignalProvider` output as `SignalFrame`.
  New strategy work should enter through
  `SignalGenerator -> SignalScoreFrame -> PortfolioAllocator ->
  TargetPortfolioFrame`, or wrap legacy `SignalFrame` output with
  `LegacyStrategyPlanner`.
- Validation layers are intentional. Configs, bar frames, signal frames, and
  report run IDs all validate inputs before downstream use.
- Reports are both human-readable and machine-readable. Future GUI tools should
  consume JSON and Parquet artifacts rather than scraping `report.html`.
- Dynamic viewers should read result files and cached bars on demand. Static
  HTML chart generation is useful for snapshots and debugging, but the preferred
  manual inspection path is `backtest chart serve-workbench`.

## Universal Trading Evolution

The new architecture separates components from the data products they emit.
The legacy `BacktestEngine -> SignalProvider -> BrokerEngine` path remains
available for existing configs. The implemented target runtime path for new
work is `StrategyPlanner -> BacktestRunner -> ExecutionBackend`.

```text
MarketDataProvider
  -> HistoricalBars / RealtimeBarSnapshot / MarketSnapshot
UniverseProvider
  -> CandidatePool
SignalGenerator
  -> SignalScoreFrame
PortfolioAllocator
  -> TargetPortfolioFrame
StrategyPlanner
  -> StrategyPlan
BacktestRunner / TradingRuntime
  -> StrategyPlanner
  -> ExecutionBackend
       -> LegacyBrokerExecutionBackend
       -> NativeSimulationBackend
OrderPlanner
  -> OrderIntent
RiskGate
  -> ApprovedOrderIntent / RejectedOrderIntent
OrderLedger
  -> OrderRecord
ExecutionAdapter / ExecutionSimulator
  -> ExecutionReport
PortfolioAccounting
  -> PortfolioState
```

This is a component map, not a single mandatory call stack. In the current
backtest runtime, `BacktestRunner` delegates to an `ExecutionBackend`; the native
backend owns the simulation details. In a future live path,
`StrategyPlan.targets` should flow through `OrderPlanner`, risk, ledger,
execution adapter, and portfolio accounting.

`SignalGenerator` answers which instruments are attractive via scores, ranks,
and signal states. `PortfolioAllocator` converts those scores into target
weights. `StrategyPlanner` orchestrates those two steps and returns a
`StrategyPlan` containing both the signal scores and target portfolio. Orders
are still created later by `OrderPlanner` from the target weights and current
portfolio state.

Backtests and live trading should share strategy, target, order intent, risk,
and portfolio contracts. `BacktestRunner` owns historical time progression and
delegates execution to an `ExecutionBackend`. During migration,
`LegacyBrokerExecutionBackend` adapts `TargetPortfolioFrame` into the current
`BrokerEngine`; `NativeSimulationBackend` is the target implementation and is
verified against the legacy backend with parity tests. Live trading should use
broker or exchange API adapters instead of either backtest backend.

## Current MVP Limitations

- `AkShareProvider` supports daily bars only.
- `CCXTOHLCVProvider` supports crypto spot historical OHLCV only; it is not a
  live trading adapter.
- Legacy `BrokerEngine` supports `next_open` execution only.
- `NativeSimulationBackend` currently mirrors the same A-share `next_open`
  semantics so parity with the legacy backend can be tested during migration.
- The run CLI is present as `backtest run --config ...`; current engine tests
  use `bars_override`, and direct cached-bar loading for CLI execution is still a
  wiring point. Programmatic `BacktestRunner` execution is available for the new
  runtime path.
