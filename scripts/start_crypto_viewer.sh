#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

HOST="${BACKTEST_VIEWER_HOST:-127.0.0.1}"
PORT="${BACKTEST_VIEWER_PORT:-8765}"
BARS_ROOT="${BACKTEST_VIEWER_BARS_ROOT:-data/crypto}"
ADJUST="${BACKTEST_VIEWER_ADJUST:-none}"
WINDOW_SIZE="${BACKTEST_VIEWER_WINDOW_SIZE:-5000}"
URL="http://${HOST}:${PORT}/"

mkdir -p runs/charts

if command -v uv >/dev/null 2>&1; then
  BACKTEST_CMD=(uv run backtest)
elif command -v backtest >/dev/null 2>&1; then
  BACKTEST_CMD=(backtest)
else
  echo "Cannot find 'uv' or an installed 'backtest' command." >&2
  echo "Install with: python -m pip install -e '.[dev]'" >&2
  exit 1
fi

if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  if command -v curl >/dev/null 2>&1 && curl -fsS "${URL}api/manifest" >/dev/null 2>&1; then
    echo "Viewer is already running. Opening existing viewer: $URL"
    if command -v open >/dev/null 2>&1; then
      open "$URL"
    fi
    exit 0
  fi
  echo "Port $PORT is already in use, but it does not look like the K-line viewer." >&2
  echo "Set BACKTEST_VIEWER_PORT to another port, for example: BACKTEST_VIEWER_PORT=8766 ./scripts/start_crypto_viewer.sh" >&2
  exit 1
fi

if command -v open >/dev/null 2>&1; then
  (sleep 2; open "$URL") >/dev/null 2>&1 &
fi

echo "Starting K-line viewer at $URL"
echo "Bars root: $BARS_ROOT"
echo "Press Ctrl-C to stop."

exec "${BACKTEST_CMD[@]}" chart serve \
  --bars-root "$BARS_ROOT" \
  --adjust "$ADJUST" \
  --host "$HOST" \
  --port "$PORT" \
  --window-size "$WINDOW_SIZE"
