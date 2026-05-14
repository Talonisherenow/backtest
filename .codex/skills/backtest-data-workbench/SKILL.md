---
name: backtest-data-workbench
description: Use when working in a Python backtest repo that has a `backtest` CLI and the user asks to submit market data crawl/sync jobs, inspect crawl task status, retry failed tasks, or open local workbench/K-line/strategy-results viewers.
---

# Backtest Data Workbench

## Overview

Use this skill to operate the local data-ingestion and visualization loop in repos modeled after `a-share-backtest`: submit data sync jobs, inspect SQLite-backed crawl/catalog state, and open the read-only chart workbench.

Core distinction: data jobs write Parquet bars and SQLite metadata; viewers only read existing result and bar files.

## Discover The Repo

1. Confirm the CLI and commands:

```bash
rg -n "sync-job|serve-workbench|serve-results|data tasks|CrawlTaskManager" README.md docs backtest tests pyproject.toml
uv run backtest data sync-job --help
uv run backtest chart serve-workbench --help
```

2. Choose the command prefix:

| Repo signal | Prefix |
| --- | --- |
| `uv.lock` exists or README uses `uv run` | `uv run backtest` |
| package installed without `uv` | `backtest` |

3. Locate paths before answering:

| Need | Search |
| --- | --- |
| job configs | `rg --files configs | rg "data_jobs|job.*ya?ml"` |
| metadata DB | `rg -n "metadata:" configs docs README.md` |
| bars root | `rg -n "bars_root|bars-root" configs docs README.md` |
| result roots | `rg -n "results-root|summary.csv|strategy-results" README.md docs runs` |

## Submit Data Crawl Jobs

For one backtest config, inspect missing ranges first, then sync:

```bash
uv run backtest data coverage --config configs/demo.yaml --metadata data/metadata.sqlite
uv run backtest data sync --config configs/demo.yaml --metadata data/metadata.sqlite --bars-root data/bars
```

For production-style batch crawling, prefer a data job YAML:

```bash
uv run backtest data sync-job --job configs/data_jobs/crypto_bitget_core.yaml
```

Typical job fields:

```yaml
name: crypto-bitget-core
source: ccxt
exchange: bitget
symbols: [BTC/USDT, ETH/USDT]
frequencies: [1d, 4h, 1h, 30m, 15m, 5m, 1m]
adjust: none
start_date: "2023-05-09"
end_date: "2026-05-08"
bars_root: data/crypto/bitget/bars
metadata: data/crypto/bitget/metadata.sqlite
output_dir: runs/crypto_market_data/bitget_core
page_delay_seconds: 0.35
retry:
  max_attempts: 5
  request_delay_seconds: 0.5
  failure_cooldown_seconds: 30
  continue_on_error: true
```

For long jobs, run in the background and persist PID/log near the job output:

```bash
mkdir -p runs/crypto_market_data/bitget_core
nohup uv run backtest data sync-job \
  --job configs/data_jobs/crypto_bitget_core.yaml \
  > runs/crypto_market_data/bitget_core/backfill.log 2>&1 &
echo $! > runs/crypto_market_data/bitget_core/backfill.pid
```

Do not start network-heavy sync jobs unless the user asked to run them. It is fine to prepare or review the job file and give the exact command.

## Check Task State

Use the metadata DB from the job/config. Do not infer status only by scanning Parquet files.

```bash
uv run backtest data tasks --metadata data/crypto/bitget/metadata.sqlite
uv run backtest data inventory --metadata data/crypto/bitget/metadata.sqlite
tail -f runs/crypto_market_data/bitget_core/backfill.log
ps -p "$(cat runs/crypto_market_data/bitget_core/backfill.pid)"
```

Interpretation:

| Signal | Meaning |
| --- | --- |
| `tasks` shows `pending`, `running`, `success`, `failed`, `retrying` | crawl lifecycle stored in SQLite |
| `inventory` shows symbol/frequency/adjust/date rows | cached coverage stored in catalog |
| job `summary.csv`/`summary.json` exists | batch job has written item-level summary, usually at exit |
| process still exists and log is moving | foreground data job is still active |

Retry failed tasks:

```bash
uv run backtest data retry --failed --metadata data/crypto/bitget/metadata.sqlite
uv run backtest data sync-job --job configs/data_jobs/crypto_bitget_core.yaml
```

The next matching sync executes `retrying` tasks before computing new missing ranges.

## Open Visualization

Prefer the combined workbench when strategy results and K-line inspection are both relevant:

```bash
uv run backtest chart serve-workbench \
  --results-root runs/ten_buy_signals/new_runtime_native_20260510 \
  --a-share-bars-root data/bars \
  --bitget-bars-root data/crypto/bitget/bars \
  --host 127.0.0.1 \
  --port 8767
```

Open:

```text
http://127.0.0.1:8767/
http://127.0.0.1:8767/strategy-results
http://127.0.0.1:8767/kline
```

Useful probes:

```bash
lsof -nP -iTCP:8767 -sTCP:LISTEN
curl -sS http://127.0.0.1:8767/api/strategy-results
curl -sS http://127.0.0.1:8767/api/manifest
curl -sS "http://127.0.0.1:8767/api/bars?source_id=a_share&symbol=000002.SZ&frequency=1d&adjust=qfq&limit=3"
```

If only K-line data matters, use the standalone viewer:

```bash
uv run backtest chart serve \
  --bars-root data/crypto \
  --adjust none \
  --host 127.0.0.1 \
  --port 8765 \
  --window-size 5000
```

Some repos include a helper such as:

```bash
./scripts/start_crypto_viewer.sh
```

## Common Mistakes

- Do not describe `/kline` or `/strategy-results` as task-control pages; they are read-only viewers.
- Do not use the wrong metadata DB. Crypto jobs often use `data/crypto/<exchange>/metadata.sqlite`; A-share jobs often use `data/metadata.sqlite`.
- Do not omit `exchange` or use adjusted bars for `source: ccxt`; CCXT jobs need `exchange` and `adjust: none`.
- Do not assume `summary.csv` updates during a long job; use tasks, inventory, process state, and logs while it runs.
- Do not kill an existing viewer just because the port is busy; probe it first and reuse it if it is the expected workbench.
- Do not manually inspect every parquet partition when `backtest data inventory` or `/api/manifest` answers the question.

## Verification Checklist

Before claiming completion:

```bash
uv run backtest data sync-job --help
uv run backtest data tasks --metadata <metadata.sqlite>
uv run backtest data inventory --metadata <metadata.sqlite>
uv run backtest chart serve-workbench --help
curl -sS http://127.0.0.1:<port>/api/manifest
```

If commands fail because the repo uses a different runner, adjust the prefix and explain the observed command shape.
