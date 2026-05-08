# K-line Cache Viewer Design

Date: 2026-05-09

## Summary

Build a standalone local K-line viewer for cached market data. The viewer should
look and behave like the existing HTML chart pages, while adding two core
capabilities:

- Switch between all cached timeframes for a selected instrument.
- Discover and select instruments from the data that actually exists on disk.

The selected implementation approach is a single static HTML file generated from
the local Parquet cache. The HTML embeds its data payload, so it can be opened
directly from `file://` without a backend service.

Implementation update on 2026-05-09: the viewer now supports multi-frequency
cache discovery, crypto spot cache inspection, a data-status drawer, and
window/position controls for navigating the bars embedded in the standalone
HTML.

## Goals

- Support cached crypto bars under layouts such as
  `data/crypto/bars/frequency=4h/adjust=none/symbol=BTC%2FUSDT/year=2025/bars.parquet`.
- Continue supporting the existing A-share daily viewer use case.
- Automatically discover available symbols, frequencies, adjust modes, years,
  row counts, and date ranges from the cache.
- Let users switch symbol, frequency, visible window size, and visible window
  position from one page.
- Add a collapsible data-status drawer that shows what has been crawled without
  permanently taking space from the main chart.
- Keep the output portable as one generated HTML file.

## Non-Goals

- No live data, WebSocket updates, credentials, or trading actions.
- No local web service for on-demand Parquet reads in this phase.
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
    `Crypto / Spot`; truly missing metadata falls back to `Unknown`.
  - Symbol selector.
  - Search box for symbol, name, exchange, or board.
  - Frequency segmented control populated from the selected symbol's cached
    frequencies.
  - `Window` select with `100`, `300`, `1000`, `5000`, and `All loaded`.
  - `Position` range slider for moving within the embedded bars.
- Summary strip:
  - Symbol, frequency, visible time span, latest visible close, visible-window
    change, and `loaded_rows / rows`.
- Main chart:
  - Plotly candlestick chart.
  - Volume subplot.
  - MA5 and MA20 overlays calculated from the currently visible bars.
- Data-status drawer:
  - Closed by default.
  - Opens from the right when the user clicks `Data Status`.
  - Lists discovered symbols and their available frequencies.
  - Shows per-symbol/per-frequency first bar, last bar, loaded rows, total rows,
    adjust mode, and cached years.
  - Clicking a symbol/frequency row switches the main chart to that data.

On narrow screens, the drawer overlays the chart instead of resizing it.
The toolbar uses a wrapping flex layout so controls do not clip each other on
wide or medium-width browser windows.

The page cannot lazily read Parquet after it is opened. The visible history is
therefore bounded by the generated payload. Use a larger `--limit` or
`--limit 0` when older bars must be browsable in the standalone HTML.

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
  "frequencies": ["1m", "5m", "15m", "30m", "60m", "4h", "1d"],
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

Extend the existing chart command rather than adding a separate tool.

Current options:

- `backtest chart viewer --bars-root data/crypto/bars --adjust none --output runs/charts/crypto_kline_viewer.html`
- `--frequency` remains available as an optional repeatable filter.
- `--symbol` and `--symbols-file` remain optional filters.
- `--limit` limits embedded chart bars per symbol/frequency series. `0` embeds
  all cached bars.
- `--universe` remains optional for A-share metadata.

When `--frequency` is omitted, the command discovers all frequencies under the
root. When `--symbol` filters are omitted, it discovers all symbols under the
root.

Current crypto inspection command:

```bash
backtest chart viewer \
  --bars-root data/crypto/bars \
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
- If Plotly fails to load at runtime, the page shows a visible chart-library
  error instead of a blank chart.

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

The HTML writer test should assert that the generated page still embeds the
payload and includes UI hooks for frequency switching, the standalone
data-status action, the drawer, and window/position navigation.

Manual verification should generate a viewer from `data/crypto/bars`, open it
locally, switch between `BTC/USDT`, `ETH/USDT`, and multiple frequencies, and
open/close the data-status drawer. The title-area Data Status button should show
the cached-series count and remain visually separate from filter controls.
