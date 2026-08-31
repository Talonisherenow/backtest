# Instrument Ops

Use this for instrument catalogs, tags/lists, source sync, and catalog-sync schedules.

## Concepts

- Instrument records are persisted market symbols with optional `source_id`, `symbol`, `name`, `market`, `exchange`, `asset_class`, `quote_currency`, and provider metadata.
- Tags/lists group instruments. The workbench uses them as watchlists and schedule targets.
- Source sync imports instruments from configured catalog sources such as `ccxt:<exchange>`, live `akshare`, and local `universe_csv`.
- Synced instrument ids are source-scoped, for example `BITGET:BTC/USDT` or `A_SHARE:000001.SZ`. The provider symbol remains in `symbol`.

## Instrument APIs

Read:

```text
GET /api/instruments?source_id=<source_id>&q=<query>&tag=<tag_id>&limit=<n>&offset=<n>
GET /api/instruments/<instrument_id>?source_id=<source_id>
GET /api/instrument-tags?source_id=<source_id>
GET /api/instrument-tags/<tag_id>/members?source_id=<source_id>
GET /api/instrument-sources
```

Write:

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
```

Write actions require confirmation. For source-scoped edits, pass `source_id` and preserve other-source memberships.

## Source Sync

Flow:

1. Read `GET /api/instrument-sources`.
2. Confirm the exact `source_id`.
3. For one-off sync, call `POST /api/instrument-sync/run` with `{"source_id":"bitget"}`.
4. Report created, updated, unchanged, failed, default tag, and sync time.

Provider notes:

- `ccxt` sources load exchange markets and skip inactive markets.
- CCXT proxy env vars can be `CCXT_PROXY`, `CCXT_HTTP_PROXY`, `CCXT_HTTPS_PROXY`, `ALL_PROXY`, `HTTP_PROXY`, or `HTTPS_PROXY`.
- `akshare` sources fetch the live A-share universe online (same shape as `backtest data universe`).
- `universe_csv` sources require a configured universe CSV path with a `symbol` column; use this for local import without network.
- CLI: `backtest data-source serve --a-share-catalog-source akshare|universe_csv` (default `akshare`). For CSV mode also pass `--a-share-universe`.
- Sync ensures the source tag/list exists and adds successfully synced instruments to it.

## Safety

- Do not delete instruments just because they disappeared from a provider catalog.
- Do not use `instrument_id` as the provider symbol for K-line or crawl jobs; use the record's `symbol`.
- Validate `source_id` before modifying instruments or tag members.
- If a source sync fails mid-batch, inspect the returned summary and tags before retrying; successful earlier upserts may already be persisted.
