# Workbench Runbook

## Local Data

```bash
uv run backtest chart serve-workbench \
  --results-root runs/ten_buy_signals/new_runtime_native_20260510 \
  --a-share-bars-root data/bars \
  --bitget-bars-root data/crypto/bitget/bars \
  --host 127.0.0.1 \
  --port 8767
```

## Remote Data Source

```bash
export BACKTEST_DATA_API_TOKEN="..."
uv run backtest chart serve-workbench \
  --results-root runs/ten_buy_signals/new_runtime_native_20260510 \
  --data-api-base-url https://data.example.com \
  --host 127.0.0.1 \
  --port 8767
```

Open:

```text
http://127.0.0.1:8767/
http://127.0.0.1:8767/kline
http://127.0.0.1:8767/strategy-results
```

Useful probes:

```bash
curl -sS http://127.0.0.1:8767/api/strategy-results
curl -sS http://127.0.0.1:8767/api/manifest
```

When `--data-api-base-url` is set, the workbench home also calls the remote data
API for `/api/data-sources`, `/api/data/tasks/summary`, `/api/data/jobs`, and
`/api/data/schedules`. It also calls `/api/data/schedules/<schedule_id>/runs`
for recent schedule triggers. The home drawer shows schedule status and recent
runs before the task table, and supports schedule enable/disable, run-now, and
basic schedule edits through the data-source HTTP API.

Security note: do not publish this local workbench to the Internet when it embeds `data_api_token`.
