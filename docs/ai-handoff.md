# AI Handoff

Read these first in a new model session:

1. `README.md`
2. `docs/architecture.md`
3. `docs/data-contracts.md`
4. `docs/cli.md`
5. Current code/tests for the area being changed

The older design docs under `docs/superpowers/specs/` are useful background,
but current code and tests supersede stale plan snippets.

## Rules For Future Sessions

- Do not document or use `backtest backtest run` as primary usage. Current CLI
  shape is `backtest run --config ...`.
- Preserve validation layers. Config models, frame validators, symbol
  normalization, signal validation, and report run ID validation are deliberate.
- Use `DataCatalog` for cache coverage and inventory. Do not infer available
  data only from raw folder names.
- Read and write market bars through `ParquetBarStore` so partitioning and frame
  validation stay centralized.
- Keep strategy code outside the core engine. Integrate it through file or
  Python signal providers and the `SignalFrame` contract.
- Do not hard-code data source behavior into broker, metrics, or reports. Data
  source specifics belong behind `DataProvider` implementations.
- Keep broker assumptions in broker/cost/slippage layers, not in signals or
  metrics.
- Future GUI tools should consume `manifest.json`, `metrics.json`, and Parquet
  outputs. Do not scrape `report.html`.
- Treat `source: akshare` and daily bars as MVP constraints, not permanent
  architecture limits.
- The run CLI exists, but direct cached-bar loading is still a wiring point in
  the current implementation. Tests may exercise `BacktestEngine` with
  `bars_override`.

## Safe Extension Map

- Add data sources by implementing `DataProvider.fetch_bars()`.
- Add cache behavior inside `ParquetBarStore`, `DataCatalog`, or
  `DataSyncService`, not in callers.
- Add signal formats by creating a provider that returns a validated
  `SignalFrame`.
- Add execution behavior by extending broker execution timing and tests.
- Add metrics through `MetricRegistry` and `MetricResult`.
- Add report consumers by reading structured JSON/Parquet files.

## Working Tree Caution

This repo may contain unrelated untracked IDE files or Python caches. Do not
touch `.idea/`, do not delete unrelated `__pycache__/` files unless the user
asks, and commit only files owned by the task.
