# K-line Cache Viewer Design

Date: 2026-05-09

## Summary

Build a standalone local K-line viewer for cached market data. The viewer should
look and behave like the existing HTML chart pages, while adding two core
capabilities:

- Switch between all cached timeframes for a selected instrument.
- Discover and select instruments from the data that actually exists on disk.

The implementation now supports two complementary modes:

- Static mode: `backtest chart viewer` writes a single HTML file with embedded
  bars, so it can be opened directly from `file://`.
- Dynamic mode: `backtest chart serve` starts a read-only local service. The
  page loads `/api/manifest` for the local data index and `/api/bars` for the
  currently selected source, symbol, frequency, and window.

Implementation update on 2026-05-09: the viewer now supports multi-frequency
cache discovery, crypto spot cache inspection, a data-status drawer, and
window/position controls for navigating the bars embedded in the standalone
HTML.

Dynamic implementation update on 2026-05-09: the viewer can also read local
Parquet windows on demand without regenerating the HTML after cache updates.

## Goals

- Support cached crypto bars under layouts such as
  `data/crypto/bitget/bars/frequency=4h/adjust=none/symbol=BTC%2FUSDT/year=2025/bars.parquet`.
- Continue supporting the existing A-share daily viewer use case.
- Automatically discover available symbols, frequencies, adjust modes, years,
  row counts, and date ranges from the cache.
- Let users switch symbol, frequency, visible window size, and visible window
  position from one page.
- Add a collapsible data-status drawer that shows what has been crawled without
  permanently taking space from the main chart.
- Keep the output portable as one generated HTML file.
- Support an optional dynamic local server for large or actively updating
  caches, while keeping it read-only against crawler-owned data.

## Non-Goals

- No live data, WebSocket updates, credentials, or trading actions.
- No advanced technical indicators beyond the current candlestick, volume, and
  simple moving averages.
- No cross-symbol comparison chart in this phase.

## User Experience

The page uses a dense research-console layout:

- Header:
  - Left side shows `K-line Cache Viewer` and dataset summary.
  - Right side has a visually distinct `Data Status` action with cached-series
    count. This is intentionally separate from the filters because it opens a
    global data inventory drawer rather than changing the chart filter.
- Filter toolbar:
  - Market / Board selector. Crypto spot symbols are classified as
    `Crypto / Spot`; truly missing metadata falls back to `Unclassified`.
  - Symbol selector.
  - Search box for symbol, name, exchange, or board.
  - Frequency segmented control populated from the selected symbol's cached
    frequencies.
- Time-window row:
  - `Window` select with `100`, `300`, `1000`, `5000`, and `All available`.
  - `Overlap` select with `0%`, `10%`, `20%`, `50%`, and `80%`; the default is
    `80%`, so adjacent `Older`/`Newer` windows share four fifths of the visible
    bars.
  - Row range, for example `Rows 4701-5000 / 5000`.
  - `Older`, `Newer`, and `Latest` buttons.
  - `Jump to` native picker for loading a window from a specific timestamp.
    Daily frequencies use a date picker; intraday frequencies use a
    datetime-local picker. The input always reflects the first visible bar's
    start time. A timestamp inside a bar resolves to that containing bar, not
    the next bar; for example, `10:02` on `5m` data resolves to `10:00`.
    Frequency and window-size changes keep the current `Jump to` value as the
    time anchor. If there are fewer bars than the requested window after that
    anchor, the viewer shows the final full window and updates `Jump to` to the
    first bar of that actual window.
  - `Position` range slider. Static mode moves within embedded bars. Dynamic
    mode maps to the full local row index for the selected symbol/frequency;
    a larger hidden buffer may be prefetched to keep nearby dragging smooth,
    but `Older` and `Newer` move by `window size * (1 - overlap)` rather than
    by the hidden buffer size.
- Summary strip:
  - Source, symbol, frequency, visible time span, latest visible close, and
    visible-window change. Row counts live in the time-window row.
- Main chart:
  - Plotly candlestick chart.
  - Volume subplot.
  - MA5 and MA20 overlays calculated from the currently visible bars.
- Data-status drawer:
  - Closed by default.
  - Opens from the right when the user clicks `Data Status`.
  - Lists discovered symbols and their available frequencies.
  - Shows per-symbol/per-frequency first bar, last bar, total rows, adjust
    mode, and cached years.
  - Clicking a symbol/frequency row switches the main chart to that data.

On narrow screens, the drawer overlays the chart instead of resizing it.
The toolbar uses a wrapping flex layout so controls do not clip each other on
wide or medium-width browser windows.

In static mode, the page cannot lazily read Parquet after it is opened. The
visible history is therefore bounded by the generated payload. Use a larger
`--limit` or `--limit 0` when older bars must be browsable in the standalone
HTML. In dynamic mode, refresh the served page or switch selections after new
Parquet files land; the service will read the latest final `bars.parquet`
partitions.

## Data Discovery

Discovery reads the cache directory, not config files. The generated page should
reflect what is currently present on disk.

The scanner should support percent-encoded symbol partition paths by using the
existing symbol path helpers from `backtest.core.symbols` where possible.

Discovery groups files by:

- `symbol`
- `frequency`
- `adjust`
- `year`

For each discovered symbol/frequency/adjust combination, it reads the relevant
Parquet files, sorts by `date`, drops duplicate `date + symbol` rows keeping the
latest row, applies the configured `limit`, and records:

- bars for charting
- `loaded_rows`, the number of bars embedded after the limit
- `rows`, the total rows before the chart limit
- first cached bar timestamp
- last cached bar timestamp
- years present

For crypto intraday data, timestamps should retain time-of-day in the payload.
Daily data can continue to display date-only labels.

## Payload Shape

The generated HTML embeds one JSON payload. The current implementation keeps the
payload top-level simple and stores richer per-frequency data under each symbol:

```json
{
  "frequency": "multi",
  "frequencies": ["1m", "5m", "15m", "30m", "1h", "4h", "1d"],
  "adjust": "none",
  "limit": 5000,
  "symbols": [
    {
      "symbol": "BTC/USDT",
      "code": "BTC/USDT",
      "name": "",
      "exchange": "Crypto",
      "board": "Spot",
      "industry": "",
      "series": [
        {
          "frequency": "4h",
          "adjust": "none",
          "rows": 1779,
          "loaded_rows": 1779,
          "first_bar": "2023-09-18T08:00:00",
          "last_bar": "2026-05-08T08:00:00",
          "years": [2023, 2024, 2025, 2026],
          "bars": []
        }
      ],
      "bars": []
    }
  ]
}
```

`bars` on the symbol is retained as a backward-compatible shortcut for the first
series; new rendering logic should use `series`.

## CLI Design

Extend the existing chart command group with static and dynamic variants.

Current options:

- `backtest chart viewer --bars-root data/crypto/bitget/bars --adjust none --output runs/charts/crypto_kline_viewer.html`
- `--frequency` remains available as an optional repeatable filter.
- `--symbol` and `--symbols-file` remain optional filters.
- `--limit` limits embedded chart bars per symbol/frequency series. `0` embeds
  all cached bars.
- `--universe` remains optional for A-share metadata.

Dynamic options:

- `backtest chart serve --bars-root data/crypto/bitget/bars --adjust none --host 127.0.0.1 --port 8765 --window-size 5000`
- `--window-size` controls the default `/api/bars` request size.
- `--frequency`, `--symbol`, `--symbols-file`, `--source-root`, and
  `--universe` have the same filtering meaning as static mode.
- When `--source-root` is omitted, both static and dynamic commands should
  inspect direct child directories under `--bars-root` and auto-discover
  `<source>/bars` roots. For example, `--bars-root data/crypto` discovers
  `data/crypto/bitget/bars` as source `bitget`.

When `--frequency` is omitted, the command discovers all frequencies under the
root. When `--symbol` filters are omitted, it discovers all symbols under the
root.

Current crypto inspection command:

```bash
backtest chart viewer \
  --bars-root data/crypto/bitget/bars \
  --output runs/charts/crypto_kline_viewer.html \
  --limit 5000 \
  --adjust none
```

`--limit 5000` is a practical default for manual intraday review. Use
`--limit 0` for full-history static inspection when large HTML output is
acceptable.

## Error Handling

- If no matching cache files exist, fail with a clear message.
- If a selected symbol has no data for a frequency, omit that frequency from the
  segmented control.
- If a Parquet partition is malformed, fail generation with the file path in the
  error so the broken cache can be fixed.
- In dynamic mode, API errors return JSON with an `error` field and the page
  shows a visible message instead of leaving the chart blank.
- If Plotly fails to load at runtime, the page shows a visible chart-library
  error instead of a blank chart.

The dynamic service only reads final `bars.parquet` files. It does not update
the Parquet cache, metadata SQLite database, or crawl task state, so it can run
beside a separate data crawling session.

## Testing

Add focused tests around the Python payload builder:

- Discovers multiple symbols and multiple frequencies from partitioned cache
  paths.
- Decodes percent-encoded crypto symbols such as `BTC%2FUSDT`.
- Preserves intraday timestamp labels for non-daily frequencies.
- Includes per-series data-status fields: rows, first/last bar, years.
- Includes `loaded_rows` so UI can distinguish embedded bars from total cached
  rows.
- Honors symbol and frequency filters.
- Keeps current A-share daily viewer behavior working.
- Dynamic service manifest indexes all local series without embedding bars.
- Dynamic service bars endpoint supports latest, explicit offset, and
  timestamp-start windows.
- CLI `chart serve` passes host, port, window size, adjust mode, universe, and
  source filters into the dynamic server.

The HTML writer test should assert that the generated page still embeds the
payload and includes UI hooks for frequency switching, the standalone
data-status action, the drawer, and window/position navigation.

Manual verification should generate a viewer from `data/crypto/bitget/bars`, open it
locally, switch between `BTC/USDT`, `ETH/USDT`, and multiple frequencies, and
open/close the data-status drawer. The title-area Data Status button should show
the cached-series count and remain visually separate from filter controls.
Dynamic manual verification should run `backtest chart serve`, open
`http://127.0.0.1:8765/crypto_kline_viewer.html`, confirm the latest window
loads by default, then use `Older`, `Newer`, `Latest`, and `Jump to` to request
other local windows without regenerating HTML.
