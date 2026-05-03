# A Share Backtest

Local, research-first MVP for A-share backtesting. The package provides a CLI,
data cache/catalog tools, signal ingestion, a simple broker model, metrics, and
structured report outputs.

## Minimal Workflow

The commands below use conventional paths. This repo does not ship
`configs/demo.yaml` or `signals/demo.csv` yet, so create those files first or
replace the paths with your own config and signal files.

Install in editable mode:

```bash
python -m pip install -e ".[dev]"
```

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

## Current Scope

- Daily A-share bars first, with frequency-aware contracts for future minute data.
- AkShare data provider for ingestion.
- Parquet bar cache plus SQLite metadata for catalog and crawl task state.
- File and Python signal providers converted to a validated `SignalFrame`.
- MVP broker with `next_open` execution, board-lot sizing, fees, slippage, T+1
  availability, suspension, and limit checks.
- Built-in metrics plus custom metrics loaded through `MetricRegistry`.
- Structured report files for future GUI consumption.

## Documentation

- [Architecture](docs/architecture.md)
- [Data ingestion](docs/data-ingestion.md)
- [Data contracts](docs/data-contracts.md)
- [Signal integration](docs/signal-integration.md)
- [Metrics extension](docs/metrics-extension.md)
- [Reports](docs/reports.md)
- [CLI](docs/cli.md)
- [AI handoff](docs/ai-handoff.md)
