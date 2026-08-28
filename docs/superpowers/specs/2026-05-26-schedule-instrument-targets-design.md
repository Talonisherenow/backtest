# Schedule Instrument Targets Design

## Goal

Upgrade data-source schedules so crawl targets are selected from known instruments instead of free-form symbol text.

## Current State

The workbench schedule editor currently stores `job.source_id` and `job.symbols` directly. `Source` is a text input and `Symbols` is a comma-separated text input. The instrument system already exposes sources, instruments, and tags through `/api/instruments`, `/api/instrument-tags`, and `/api/instrument-sources`, but data schedules do not use those records for validation or target expansion.

## Requirements

- A schedule target must resolve to instruments already present in the instrument store.
- The schedule editor `Source` field must be a dropdown built from available data/instrument sources.
- The schedule editor `Symbols` field must support two modes:
  - Search existing instruments and select individual instruments.
  - Select an instrument List/tag and run the same schedule configuration for all members.
- Existing schedules that use `job.symbols` must keep working.
- List/tag schedules should resolve dynamically at run time so future List membership changes affect later runs.
- The crawl job must receive provider symbols from `InstrumentRecord.symbol`, not `instrument_id`.

## Recommended Data Contract

Add optional `job.target` to schedule job templates while keeping legacy `job.symbols`.

```json
{
  "job": {
    "source_id": "bitget",
    "target": {
      "mode": "tag",
      "tag_id": "watchlist",
      "resolution": "dynamic"
    },
    "frequencies": ["1h"],
    "date_range": {
      "type": "last_n_days",
      "lookback_value": 7,
      "lookback_unit": "days"
    }
  }
}
```

Individual instrument mode:

```json
{
  "target": {
    "mode": "symbols",
    "instrument_ids": ["BITGET:BTC/USDT", "BITGET:ETH/USDT"]
  }
}
```

## Backend Design

`ScheduleJobTemplate` accepts either legacy `symbols` or a new `target`. `DataSourceScheduleService` receives a symbol resolver callback. During create/update/run, the resolver:

- Validates `source_id` exists.
- For `mode=symbols`, validates all `instrument_ids` exist and belong to `source_id`.
- For `mode=tag`, validates the tag exists and resolves members that belong to `source_id`.
- Returns the provider symbols to pass to `DataSyncJobConfig.symbols`.

Legacy `job.symbols` remains supported and continues to be validated by the existing schedule payload path.

Add `GET /api/instrument-tags/<tag_id>/members?source_id=<source_id>` so the workbench can preview List membership without abusing paginated instrument search.

## Workbench Design

In `Edit Schedule`:

- `Source` becomes a select.
- `Symbols` becomes a target picker with two modes:
  - `Search Symbols`: search `/api/instruments?source_id=<id>&q=<query>&limit=20`, select instruments, show selected chips.
  - `Use List`: select `/api/instrument-tags?source_id=<id>`, show member count and preview members.
- Changing `Source` clears the selected target.
- Schedule rows render target summaries:
  - `bitget · BTC/USDT, ETH/USDT · 1h`
  - `bitget · List: Watchlist (32 symbols) · 1h`

## Error Handling

- Save fails if the target resolves to zero symbols.
- Save fails if any selected instrument belongs to a different source.
- Save fails if a selected List/tag does not exist.
- For remote servers older than this contract, the UI should fall back to legacy `symbols` display for existing schedules and surface API errors on save.

## Testing

- Unit tests for target model validation.
- API tests for tag member listing.
- Schedule service tests for:
  - Target symbols resolve to provider symbols.
  - Tag targets resolve dynamically at run time.
  - Source mismatches are rejected.
  - Legacy `symbols` schedules still work.
- Workbench rendering tests for target payload presence and editor controls.
