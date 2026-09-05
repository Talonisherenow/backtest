# Instrument API

Use this for IM requests about instruments, tags/lists, source catalog sync, and instrument sync schedules. The IM agent remains API-only.

## Read Endpoints

```text
GET /api/instruments?source_id=<source_id>&q=<query>&tag=<tag_id>&limit=<n>&offset=<n>
GET /api/instruments/<instrument_id>?source_id=<source_id>
GET /api/instrument-tags?source_id=<source_id>
GET /api/instrument-tags/<tag_id>/members?source_id=<source_id>
GET /api/instrument-sources
GET /api/instrument-sync/schedules
GET /api/instrument-sync/schedules/<schedule_id>
GET /api/instrument-sync/schedules/<schedule_id>/runs
```

## Write Endpoints

Require explicit confirmation before calling:

```text
POST   /api/instruments
PATCH  /api/instruments/<instrument_id>
DELETE /api/instruments/<instrument_id>
POST   /api/instrument-tags
PATCH  /api/instrument-tags/<tag_id>
DELETE /api/instrument-tags/<tag_id>
PUT    /api/instrument-tags/<tag_id>/members
POST   /api/instrument-tags/<tag_id>/members
DELETE /api/instrument-tags/<tag_id>/members/<instrument_id>
POST   /api/instrument-sync/run
POST   /api/instrument-sync/schedules
PATCH  /api/instrument-sync/schedules/<schedule_id>
DELETE /api/instrument-sync/schedules/<schedule_id>
POST   /api/instrument-sync/schedules/<schedule_id>/enable
POST   /api/instrument-sync/schedules/<schedule_id>/disable
POST   /api/instrument-sync/schedules/<schedule_id>/run-now
```

## Rules

- Use `source_id` filters when the user names a market/source such as Bitget or A-share.
- `instrument_id` is source-scoped for synced instruments, e.g. `BITGET:BTC/USDT`.
- K-line and crawl jobs use `InstrumentRecord.symbol`, not `instrument_id`.
- Tag/list targets can be source-filtered; preserve other-source tag members when modifying one source.
- `POST /api/instrument-sync/run` refreshes the instrument catalog, not K-line bars.
- Instrument sync schedules refresh instruments/tags; data crawl schedules submit K-line crawl jobs.
- Before syncing, read `GET /api/instrument-sources` and report `provider_type`:
  - `ccxt`: live exchange catalog
  - `akshare`: live A-share catalog (online)
  - `universe_csv`: local CSV catalog (offline import; path in `provider_config`)
- Switching A-share catalog mode (`akshare` ↔ `universe_csv`) requires restarting
  `data-source serve` with `--a-share-catalog-source`. That is outside the IM API.

## Common Flows

Search instruments:

1. Call `GET /api/instruments?source_id=<source_id>&q=<query>&limit=20`.
2. Return symbol, name, source, asset class, quote currency, and tag/list membership.

Create or update a list:

1. Confirm tag/list name, color, optional description, and source scope.
2. Call tag write endpoint after confirmation.
3. Read back `/api/instrument-tags` or members to report final state.

Sync instrument source:

1. Read `GET /api/instrument-sources`.
2. Confirm exact `source_id` and tell the user the current `provider_type`
   (`ccxt`, `akshare`, or `universe_csv`).
3. Call `POST /api/instrument-sync/run` only after confirmation.
4. Report created, updated, unchanged, failed, default tag, and sync time.
5. Remind that new instruments appear in K-line crawls only after a data
   schedule targets them (usually the default source tag) and that schedule runs.

Create instrument sync schedule:

1. Confirm this is catalog sync, not K-line crawl.
2. Confirm source, trigger, timezone, repeat policy, and enabled state.
3. Call `POST /api/instrument-sync/schedules` only after confirmation.
4. If the user also wants recurring bars, point them to data crawl schedules
   (`/api/data/schedules`) with `job.target.mode=tag` on the source default tag.
