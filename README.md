# A Share Backtest

Local, research-first backtesting workbench. The package provides a CLI, market
data cache/catalog tools, legacy signal ingestion, a new strategy-planning and
runtime layer, A-share simulation backends, metrics, structured report outputs,
and local viewers for K-line plus strategy results inspection.

## Quick Start

Install in editable mode with development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Run the test suite:

```bash
uv run pytest -q
```

Start the combined local workbench:

```bash
uv run backtest chart serve-workbench \
  --results-root runs/ten_buy_signals/new_runtime_native_20260510 \
  --a-share-bars-root data/bars \
  --bitget-bars-root data/crypto/bitget/bars \
  --host 127.0.0.1 \
  --port 8767
```

Then open:

```text
http://127.0.0.1:8767/
```

Workbench routes:

- `/` opens the workbench home.
- `/strategy-results` opens the dynamic strategy results catalog.
- `/kline` opens the dynamic cached K-line viewer.

The workbench is the preferred manual inspection entrypoint. It reads existing
result files and cached bars on demand; normal backtest runs do not need to
generate HTML files first.

## Current Runtime Shape

New strategy work should use the strategy-planning path:

```text
SignalGenerator -> SignalScoreFrame
PortfolioAllocator -> TargetPortfolioFrame
StrategyPlanner -> StrategyPlan
BacktestRunner -> ExecutionBackend
```

Implemented backtest execution backends:

- `NativeSimulationBackend`: target native A-share simulation path.
- `LegacyBrokerExecutionBackend`: compatibility backend wrapping the legacy
  `BrokerEngine` for parity checks during migration.

Existing legacy configs can still use:

```text
BacktestEngine -> SignalProvider -> BrokerEngine
```

That legacy path is retained for compatibility and regression checks, but it is
not the preferred extension point for new strategies.

## Ten Buy Signals

The current branch contains a new-runtime integration path for the "ten buy
signals" strategy family. The first migrated result batch lives at:

```text
runs/ten_buy_signals/new_runtime_native_20260510/
```

Expected aggregate files:

```text
summary.csv
summary.json
orders.csv
trades.csv
equity_curve.csv
signals.csv
targets.csv
failures.json
```

The dynamic Strategy Results catalog scans result roots for `summary.csv` and
loads orders, equity, and K-line data only when a user opens a strategy result.

## Useful Commands

Validate a config and signal file:

```bash
backtest validate config --config configs/demo.yaml
backtest validate signals --path signals/demo.csv --symbol 000001.SZ
```

Sync missing market data:

```bash
backtest data coverage --config configs/demo.yaml --metadata data/metadata.sqlite
backtest data sync --config configs/demo.yaml --metadata data/metadata.sqlite --bars-root data/bars
backtest data inventory --metadata data/metadata.sqlite
```

Run command shape:

```bash
backtest run --config configs/demo.yaml
```

Note: the current CLI entrypoint accepts `backtest run --config ...`. Older plan
snippets that mention `backtest backtest run` are stale.

Direct cached-bar loading for CLI backtest runs is still a wiring point in this
MVP, so the command currently exits with a cached-bar loading message instead of
running end to end. Engine-level tests exercise backtests with explicit bar data.

Serve only the dynamic strategy results viewer:

```bash
uv run backtest chart serve-results \
  --results-root runs/ten_buy_signals/new_runtime_native_20260510 \
  --bars-root data/bars \
  --host 127.0.0.1 \
  --port 8766
```

Serve only the dynamic K-line viewer:

```bash
uv run backtest chart serve \
  --bars-root data/crypto \
  --adjust none \
  --host 127.0.0.1 \
  --port 8765
```

Static HTML chart commands still exist for debugging or snapshot artifacts, but
they are no longer the normal strategy-results workflow.

## Crypto Data And Viewer

Run the configured Bitget crypto data job:

```bash
uv run backtest data sync-job --job configs/data_jobs/crypto_bitget_core.yaml
```

Check crawl tasks and cached inventory:

```bash
uv run backtest data tasks --metadata data/crypto/bitget/metadata.sqlite
uv run backtest data inventory --metadata data/crypto/bitget/metadata.sqlite
```

Start the dynamic local K-line viewer with the helper from `main`:

```bash
./scripts/start_crypto_viewer.sh
```

Detailed operating notes are in [Market data operations](docs/market-data-operations.md).

## Current Scope

- Daily A-share bars first, with frequency-aware contracts for future minute data.
- AkShare data provider for ingestion.
- Parquet bar cache plus SQLite metadata for catalog and crawl task state.
- CCXT crypto spot historical OHLCV ingestion and source-aware cache viewer.
- File and Python signal providers converted to a validated legacy
  `SignalFrame`.
- New strategy-planning path:
  `SignalGenerator -> PortfolioAllocator -> StrategyPlanner`.
- New runtime path:
  `BacktestRunner -> ExecutionBackend`, with both legacy BrokerEngine
  compatibility and native simulation backends.
- A-share simulation with `next_open` execution, board-lot sizing, fees,
  slippage, T+1 availability, suspension, and limit checks.
- Built-in metrics plus custom metrics loaded through `MetricRegistry`.
- Structured report files for future GUI consumption.
- Dynamic chart workbench for Strategy Results and K-line inspection.

## Artifact Policy

Source code, tests, architecture docs, specs, and plans belong in git. Generated
runtime outputs and local data caches generally should not be committed unless a
review explicitly asks for sample artifacts:

```text
runs/
data/crypto/
.superpowers/
```

The A-share sample data under `data/bars/` and existing universe fixtures are
part of the current local research setup; check `git status --short` before
staging to avoid mixing generated files with source changes.

## Documentation

- [Architecture](docs/architecture.md)
- [Data ingestion](docs/data-ingestion.md)
- [Data contracts](docs/data-contracts.md)
- [Signal integration](docs/signal-integration.md)
- [Metrics extension](docs/metrics-extension.md)
- [Reports](docs/reports.md)
- [CLI](docs/cli.md)
- [Strategy planning architecture handoff](docs/2026-05-11-strategy-planning-architecture-handoff.md)
- [AI handoff](docs/ai-handoff.md)
