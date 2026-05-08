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

## Goals

- Support cached crypto bars under layouts such as
  `data/crypto/bars/frequency=4h/adjust=none/symbol=BTC%2FUSDT/year=2025/bars.parquet`.
- Continue supporting the existing A-share daily viewer use case.
- Automatically discover available symbols, frequencies, adjust modes, years,
  row counts, and date ranges from the cache.
- Let users switch symbol, frequency, and visible range from one page.
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

The page uses the A-style high-density trading-desk layout:

- Top toolbar:
  - Market/source selector when multiple cache roots or datasets are present.
  - Symbol selector with search.
  - Frequency segmented control populated from the selected symbol's cached
    frequencies.
  - Range buttons such as `60`, `120`, `300`, and `All`.
  - A `Data Status` button.
- Summary strip:
  - Symbol, frequency, date range, latest close, range change, latest volume,
    and cached row count.
- Main chart:
  - Plotly candlestick chart.
  - Volume subplot.
  - MA5 and MA20 overlays calculated from the currently visible bars.
- Data-status drawer:
  - Closed by default.
  - Opens from the right when the user clicks `Data Status`.
  - Lists discovered symbols and their available frequencies.
  - Shows per-symbol/per-frequency rows, first bar, last bar, adjust mode, and
    cached years.
  - Clicking a symbol/frequency row switches the main chart to that data.

On narrow screens, the drawer overlays the chart instead of resizing it.

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
- total rows before the chart limit
- first cached bar timestamp
- last cached bar timestamp
- years present

For crypto intraday data, timestamps should retain time-of-day in the payload.
Daily data can continue to display date-only labels.

## Payload Shape

The generated HTML embeds one JSON payload:

```json
{
  "datasets": [
    {
      "name": "crypto",
      "bars_root": "data/crypto/bars",
      "symbols": [
        {
          "symbol": "BTC/USDT",
          "name": "",
          "market": "crypto",
          "series": [
            {
              "frequency": "4h",
              "adjust": "none",
              "rows": 1779,
              "first_bar": "2023-09-18T08:00:00",
              "last_bar": "2026-05-08T08:00:00",
              "years": [2023, 2024, 2025, 2026],
              "bars": []
            }
          ]
        }
      ]
    }
  ]
}
```

The implementation can keep backward-compatible top-level fields for current
tests, but the page should render from the richer dataset/series model.

## CLI Design

Extend the existing chart command rather than adding a separate tool.

Proposed options:

- `backtest chart viewer --bars-root data/crypto/bars --adjust none --output runs/charts/crypto_kline_viewer.html`
- `--frequency` remains available as an optional repeatable filter.
- `--symbol` and `--symbols-file` remain optional filters.
- `--limit` limits embedded chart bars per symbol/frequency series.
- `--universe` remains optional for A-share metadata.

When `--frequency` is omitted, the command discovers all frequencies under the
root. When `--symbol` filters are omitted, it discovers all symbols under the
root.

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
- Honors symbol and frequency filters.
- Keeps current A-share daily viewer behavior working.

The HTML writer test should assert that the generated page still embeds the
payload and includes UI hooks for frequency switching and the data-status drawer.

Manual verification should generate a viewer from `data/crypto/bars`, open it
locally, switch between `BTC/USDT`, `ETH/USDT`, and multiple frequencies, and
open/close the data-status drawer.
