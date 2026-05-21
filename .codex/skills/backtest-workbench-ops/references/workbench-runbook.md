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

When the user provides a token for repeated workbench use, persist it without
printing the value:

```bash
mkdir -p "$HOME"
cat > "$HOME/.backtest-env" <<'EOF'
export BACKTEST_DATA_API_TOKEN="..."
EOF
chmod 600 "$HOME/.backtest-env"

for shell_file in "$HOME/.zshrc" "$HOME/.zprofile"; do
  touch "$shell_file"
  if ! grep -q 'HOME/.backtest-env' "$shell_file"; then
    cat >> "$shell_file" <<'EOF'

if [ -f "$HOME/.backtest-env" ]; then
  . "$HOME/.backtest-env"
fi
EOF
  fi
done
```

Restart the workbench with the token coming from the environment, not from the
command line:

```bash
zsh -lc 'uv run backtest chart serve-workbench \
  --results-root runs/ten_buy_signals/new_runtime_native_20260510 \
  --data-api-base-url https://data.example.com \
  --host 127.0.0.1 \
  --port 8767'
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
zsh -lc 'curl -sS -o /tmp/backtest-schedules-check.json -w "%{http_code}\n" \
  -H "Authorization: Bearer $BACKTEST_DATA_API_TOKEN" \
  https://data.example.com/api/data/schedules'
zsh -lc 'curl -sS \
  -H "Authorization: Bearer $BACKTEST_DATA_API_TOKEN" \
  https://data.example.com/api/data/schedule-options'
```

When `--data-api-base-url` is set, the workbench home also calls the remote data
API for `/api/data-sources`, `/api/data/tasks/summary`, `/api/data/jobs`, and
`/api/data/schedules`. It also calls `/api/data/schedules/<schedule_id>/runs`
for recent schedule triggers. The home drawer shows schedule status and recent
runs before the task table, and supports schedule enable/disable, run-now, and
basic schedule edits through the data-source HTTP API.

Current monitor expectations:

- The data-source panel opens from the top and uses tabs for `Schedules` and
  `Crawl Tasks`.
- Schedules, recent schedule runs, and crawl tasks each have their own
  pagination controls.
- Schedule mutation buttons confirm before enable/disable, and enable/disable
  state should be visually obvious.
- The schedule editor keeps `start_at` and `run_at` as one native
  `datetime-local` input, uses a compact trigger row, and shows frequencies in
  a dropdown multi-select with the selected values visible.
- The friendly range presets `Last N mins`, `Last N hours`, and `Last N days`
  are UI labels for the API shape
  `{"type":"last_n_days","lookback_value":N,"lookback_unit":"minutes|hours|days"}`.
- Execution delay is `trigger.execution_delay_seconds`: it delays submission
  after the scheduled anchor. Request gap is `job.page_delay_seconds`: it delays
  provider page requests inside a crawl.

Before blaming the workbench for schedule-save behavior, confirm the remote
server supports the same schedule contract as the UI:

```bash
zsh -lc 'curl -sS \
  -H "Authorization: Bearer $BACKTEST_DATA_API_TOKEN" \
  https://data.example.com/api/data/schedule-options | rg "execution_delay_units|range_units|seconds"'
```

If an execution-delay edit returns HTTP 200 but the response omits
`config.trigger.execution_delay_seconds`, the remote data-source server is old.
Deploy or restart the updated data-source API before testing that field again.

Security note: do not publish this local workbench to the Internet when it embeds `data_api_token`.
