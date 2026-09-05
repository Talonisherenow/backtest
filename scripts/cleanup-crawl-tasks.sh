#!/bin/bash
# Retain only recent crawl_tasks rows in metadata SQLite DBs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

RETAIN_DAYS="${RETAIN_DAYS:-3}"
# Default --no-vacuum so the daily LaunchAgent can run while data-source is up.
# Pass VACUUM_FLAG=--vacuum after stopping data-source when reclaiming disk.
VACUUM_FLAG="${VACUUM_FLAG:---no-vacuum}"

run_one() {
  local metadata="$1"
  if [[ ! -f "$metadata" ]]; then
    echo "skip missing metadata: $metadata"
    return 0
  fi
  /usr/local/bin/uv run -- backtest data cleanup-tasks \
    --metadata "$metadata" \
    --retain-days "$RETAIN_DAYS" \
    "$VACUUM_FLAG"
}

run_one "data/crypto/bitget/metadata.sqlite"
run_one "data/metadata.sqlite"
