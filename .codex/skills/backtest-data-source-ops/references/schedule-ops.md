# Schedule Ops

Use this for data crawl schedules and instrument sync schedules. Writes require explicit confirmation.

## Data Crawl Schedules

Read:

```text
GET /api/data/schedule-options
GET /api/data/schedules
GET /api/data/schedules/<schedule_id>
GET /api/data/schedules/<schedule_id>/runs?limit=<n>
```

Write:

```text
POST   /api/data/schedules
PATCH  /api/data/schedules/<schedule_id>
DELETE /api/data/schedules/<schedule_id>
POST   /api/data/schedules/<schedule_id>/enable
POST   /api/data/schedules/<schedule_id>/disable
POST   /api/data/schedules/<schedule_id>/run-now
```

Call `GET /api/data/schedule-options` before creating or updating schedules when supported sources, frequencies, trigger units, repeat modes, or range units are unknown.

`GET /api/data/schedules` is compact: when a job uses an instrument `target`,
legacy `job.symbols` is omitted from the list payload. Fetch a single schedule
for the full stored config.

`GET .../runs` defaults to `limit=50` (newest first, max 200).

## Schedule Targets

Prefer instrument-backed targets when the request refers to known instruments or a saved list.

Individual instruments:

```json
{
  "job": {
    "source_id": "bitget",
    "target": {
      "mode": "symbols",
      "instrument_ids": ["BITGET:BTC/USDT", "BITGET:ETH/USDT"]
    },
    "frequencies": ["1h"],
    "date_range": {"type": "last_n_days", "lookback_value": 7, "lookback_unit": "days"}
  }
}
```

List/tag target:

```json
{
  "job": {
    "source_id": "bitget",
    "target": {"mode": "tag", "tag_id": "watchlist", "resolution": "dynamic"},
    "frequencies": ["1h"],
    "date_range": {"type": "last_n_days", "lookback_value": 7, "lookback_unit": "days"}
  }
}
```

Rules:

- Legacy `job.symbols` still works, but new schedules should use `job.target` when instruments or lists exist.
- `target.mode=symbols` uses `instrument_ids`, not provider symbols.
- `target.mode=tag` resolves dynamically at run time; later list membership changes affect future runs.
- The backend resolves final crawl symbols from `InstrumentRecord.symbol`.
- `source_id` must match every selected instrument. Reject cross-source schedules instead of silently mixing symbols.
- If a tag resolves to zero source-matching instruments, do not create/run the schedule until the target is corrected.

## Trigger And Range Rules

- Trigger types: `once`, `interval`, `daily`, `weekly`.
- Interval units: `seconds`, `minutes`, `hours`, `days`.
- Repeat modes: `forever`, `count`, `until`.
- Default timezone: `Asia/Shanghai`.
- `trigger.execution_delay_seconds` delays submission after the scheduled anchor. It is not request throttling.
- `job.page_delay_seconds` throttles provider page requests inside the crawl job.
- UI labels `Last N mins/hours/days` map to `date_range.type=last_n_days` plus `lookback_value` and `lookback_unit=minutes|hours|days`.
- `job.refresh_existing` defaults to `true` for schedules; keep it true for recurring intraday refreshes.

## Instrument Sync Schedules

Instrument sync schedules refresh the instrument catalog itself. They do not crawl K-line bars.

Read:

```text
GET /api/instrument-sync/schedules
GET /api/instrument-sync/schedules/<schedule_id>
GET /api/instrument-sync/schedules/<schedule_id>/runs
```

Write:

```text
POST   /api/instrument-sync/schedules
PATCH  /api/instrument-sync/schedules/<schedule_id>
DELETE /api/instrument-sync/schedules/<schedule_id>
POST   /api/instrument-sync/schedules/<schedule_id>/enable
POST   /api/instrument-sync/schedules/<schedule_id>/disable
POST   /api/instrument-sync/schedules/<schedule_id>/run-now
```

Minimal payload:

```json
{
  "name": "bitget-instrument-sync",
  "enabled": false,
  "source_id": "bitget",
  "trigger": {"type": "interval", "every": 1, "unit": "days", "timezone": "Asia/Shanghai"},
  "repeat": {"mode": "forever"}
}
```

A-share catalog sync example (requires live `provider_type=akshare` on the
running data-source process):

```json
{
  "name": "a-share-instrument-sync",
  "enabled": false,
  "source_id": "a_share",
  "trigger": {"type": "interval", "every": 1, "unit": "days", "timezone": "Asia/Shanghai"},
  "repeat": {"mode": "forever"}
}
```

Do not confuse instrument sync schedules with data crawl schedules: instrument sync updates instruments/tags; data crawl schedules submit K-line crawl jobs.

Typical orchestration for “keep listings fresh, then crawl bars”:

1. Enable an instrument-sync schedule for the source (`bitget` or `a_share`).
2. Keep a data crawl schedule whose `job.target` is the source default tag
   (`tag_id=bitget` or `tag_id=a_share`, `resolution=dynamic`).
3. Use A-share crawl frequencies `[1d]`; Bitget commonly uses `[1d, 4h, 1h]`.
4. Confirm `/api/instrument-sources` shows the expected `provider_type` before
   treating catalog sync as live.
