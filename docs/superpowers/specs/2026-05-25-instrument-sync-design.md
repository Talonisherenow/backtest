# Instrument Source Sync Design

Date: 2026-05-25
Status: draft for review
Branch: `feat/instrument-tags-http`

## 1. Background

The data-source backend already exposes HTTP APIs for instrument records and
instrument tags/lists. The workbench can show all instruments, create custom
lists, add instruments to lists, and open the selected instrument in the K-line
viewer.

The current instrument inventory is still manually created or temporarily
seeded from the K-line manifest. The next step is to make the data-source
backend understand where instrument definitions come from, then support manual
and scheduled synchronization from those sources.

The first concrete sources are:

- Bitget, read through CCXT market metadata.
- A-share, read from the configured local universe file.

The design must also support adding more CCXT exchanges later, such as Binance
or OKX, without hard-coding one provider class per exchange.

## 2. Goals

- Expose a data-source inventory endpoint that shows which sources can provide
  instrument lists.
- Add an abstraction for reading instrument catalogs from provider types such as
  `ccxt` and local universe files.
- Support manual HTTP-triggered synchronization from one source into the
  persisted instrument list.
- Support scheduled synchronization from one source into the persisted
  instrument list.
- Keep the instrument list as the default global inventory. The workbench `All`
  list remains a virtual filter for every persisted instrument.
- Automatically create and maintain one real tag/list per synced source, such as
  `Bitget` or `A-share`.
- Add newly synced instruments to the matching source tag/list.
- Keep this HTTP-only. No new CLI commands are added for instrument sync.
- Preserve existing workbench K-line links by keeping each instrument's original
  provider symbol.

## 3. Non-Goals

- No strategy, portfolio, order, or execution behavior changes.
- No new CLI management surface for providers or schedules.
- No distributed job queue or external scheduler dependency.
- No provider credential management in the first version.
- No full editable provider registry UI in the first version.
- No deletion of instruments that disappear from a provider catalog. A missing
  provider item should be treated as absent from the latest sync result, not as a
  command to remove local records.

## 4. Concepts

### 4.1 Provider Type

`provider_type` is the implementation family used to read an instrument
catalog. It answers "how do we fetch a list of tradable instruments?"

First supported values:

- `ccxt`: uses the CCXT package and an exchange id.
- `universe_csv`: reads a local configured CSV universe file.

### 4.2 Source ID

`source_id` is a concrete configured data-source instance. It answers "which
source in this server are we syncing?"

Example:

```json
{
  "source_id": "bitget",
  "source_label": "Bitget",
  "provider_type": "ccxt",
  "provider_config": {
    "exchange": "bitget"
  }
}
```

Multiple source ids can share the same provider type:

```json
[
  {
    "source_id": "bitget",
    "provider_type": "ccxt",
    "provider_config": {"exchange": "bitget"}
  },
  {
    "source_id": "binance",
    "provider_type": "ccxt",
    "provider_config": {"exchange": "binance"}
  }
]
```

The CCXT provider implementation dynamically resolves the exchange from
`provider_config.exchange`, then calls `load_markets()` and normalizes the
returned market metadata into the system instrument shape.

### 4.3 Instrument Identity

The system needs to support the same symbol appearing in multiple source
instances. For sync-created records, the canonical `instrument_id` is
source-scoped:

```text
bitget:BTC/USDT
binance:BTC/USDT
a_share:000001.SZ
```

Each record still stores the provider symbol separately:

```json
{
  "instrument_id": "bitget:BTC/USDT",
  "symbol": "BTC/USDT",
  "source_id": "bitget"
}
```

Workbench K-line navigation uses `source_id` plus `symbol`, so existing chart
behavior stays aligned with the cached bar APIs.

Manually created records can keep their existing ids. The source-scoped id rule
is only required for synchronized records so multiple providers can coexist
without collisions.

### 4.4 Source Tags

The persisted instrument table is the default global inventory. The workbench
`All` entry remains virtual and maps to "all persisted instruments".

Each sync-capable source gets a real tag/list:

- `bitget` source creates or updates a `Bitget` tag.
- `a_share` source creates or updates an `A-share` tag.

After a sync run, every instrument returned by that source is added to the
source tag. Existing user-created tags, such as `自选`, are not modified.

## 5. Architecture

### 5.1 Provider Layer

Add a focused module for instrument catalog sync, for example
`backtest.data_source.instrument_sync`.

Main data structures:

```python
@dataclass(frozen=True)
class InstrumentSourceDefinition:
    source_id: str
    source_label: str
    asset_class: str
    provider_type: str
    provider_config: dict[str, object]
    default_tag_id: str
    default_tag_name: str


@dataclass(frozen=True)
class InstrumentCatalogItem:
    instrument_id: str
    symbol: str
    name: str | None
    market: str | None
    exchange: str | None
    asset_class: str | None
    quote_currency: str | None
    metadata: dict[str, object]
```

Provider interface:

```python
class InstrumentCatalogProvider(Protocol):
    def list_instruments(self) -> list[InstrumentCatalogItem]:
        ...
```

Provider implementations:

- `CCXTInstrumentCatalogProvider`
  - Accepts `exchange_id`.
  - Creates `getattr(ccxt, exchange_id)()`.
  - Calls `load_markets()`.
  - Filters out inactive markets when CCXT marks them inactive.
  - Normalizes symbols, base, quote, market type, exchange id, and raw metadata.
- `UniverseCsvInstrumentCatalogProvider`
  - Reads the configured A-share universe CSV.
  - Uses columns such as `symbol`, `name`, `exchange`, `board`, and `industry`
    when available.
  - Produces equity instruments with `source_id=a_share`.

### 5.2 Sync Service

`InstrumentSyncService` owns the orchestration:

1. Resolve the source definition from `DataSourceServerConfig`.
2. Build the matching provider from `provider_type`.
3. Read provider catalog items.
4. Upsert instruments into the global instrument store.
5. Ensure the source tag exists.
6. Add synced instrument ids to the source tag.
7. Return a JSON-serializable summary.

Result shape:

```json
{
  "source_id": "bitget",
  "status": "success",
  "created": 10,
  "updated": 2,
  "unchanged": 300,
  "failed": 0,
  "tag_id": "bitget",
  "synced_at": "2026-05-25T12:00:00+08:00"
}
```

If a provider raises an error, the HTTP response should be a 400 for expected
configuration/provider errors and a 500 for unexpected failures, matching the
existing data-source server style.

### 5.3 Global Instrument Store

The existing instrument APIs should keep their current route shapes. Internally,
instrument sync should use one shared instrument store for all sources rather
than one separate instrument database per source.

The first implementation can use the first configured source metadata database
as the shared instrument store to stay compatible with the existing schema and
deployment model. A later migration can introduce an explicit
`instrument_metadata_path` if the server needs a separate inventory database.

The store needs two small additions:

- `upsert_instrument(payload)` returning whether the record was created,
  updated, or unchanged.
- `ensure_tag(payload)` returning the existing or newly created tag.

These methods are store-level primitives used by sync and are not separate HTTP
routes.

### 5.4 Schedule Service

Instrument sync schedules are separate from K-line crawl schedules because the
job payload is much smaller: a source id plus a trigger.

Use the existing schedule database path, but store instrument sync schedules in
dedicated tables:

- `instrument_sync_schedules`
- `instrument_sync_schedule_runs`

First version trigger support:

```json
{
  "name": "bitget-instruments-hourly",
  "enabled": true,
  "source_id": "bitget",
  "trigger": {
    "type": "interval",
    "every": 1,
    "unit": "hours",
    "start_at": "2026-05-25T09:00:00+08:00",
    "timezone": "Asia/Shanghai"
  }
}
```

Supported trigger types should match the existing data scheduler where practical:

- `once`
- `interval`
- `daily`
- `weekly`

The schedule service computes `next_run_at`, records run history, and calls
`InstrumentSyncService.sync_source(source_id)` when due. This keeps provider
sync logic in one place.

## 6. HTTP API

All routes use the existing bearer-token authorization and JSON error style.

### 6.1 Source Discovery

```text
GET /api/instrument-sources
```

Returns the sync-capable sources:

```json
{
  "sources": [
    {
      "source_id": "bitget",
      "source_label": "Bitget",
      "asset_class": "crypto",
      "provider_type": "ccxt",
      "provider_config": {"exchange": "bitget"},
      "default_tag_id": "bitget",
      "default_tag_name": "Bitget"
    }
  ]
}
```

### 6.2 Manual Sync

```text
POST /api/instrument-sync/run
```

Request:

```json
{"source_id": "bitget"}
```

Response is the sync result summary.

### 6.3 Schedule Management

```text
GET    /api/instrument-sync/schedules
POST   /api/instrument-sync/schedules
GET    /api/instrument-sync/schedules/{schedule_id}
PATCH  /api/instrument-sync/schedules/{schedule_id}
DELETE /api/instrument-sync/schedules/{schedule_id}
POST   /api/instrument-sync/schedules/{schedule_id}/enable
POST   /api/instrument-sync/schedules/{schedule_id}/disable
POST   /api/instrument-sync/schedules/{schedule_id}/run-now
GET    /api/instrument-sync/schedules/{schedule_id}/runs
```

These mirror the existing data schedule route conventions, but they operate on
instrument sync schedules and call the instrument sync service.

## 7. Workbench UI

The `/instruments` page gains one compact entry near the existing top actions:
`Sources` or `Sync`.

Clicking it opens a modal with:

- Sync-capable source list.
- Provider type and provider config summary.
- `Sync Now` button per source.
- A small schedule form for source, trigger type, interval number, interval
  unit, and enabled state.
- Existing schedule list with enable, disable, run now, and delete actions.
- Latest result or error message.

After manual sync or schedule run-now completes, the page reloads instruments,
tags, source filters, and pagination counts.

The page should keep its current operational layout. This feature adds a source
sync modal rather than a new route.

## 8. Error Handling

- Unknown `source_id` returns HTTP 400.
- Unsupported `provider_type` returns HTTP 400.
- Unknown CCXT exchange id returns HTTP 400.
- Provider fetch failure is reported in the sync result when it is recoverable;
  unrecoverable setup errors return HTTP 400 or 500 according to the existing
  server exception handling pattern.
- Schedule run failures are recorded in schedule run history and surfaced in the
  schedule list.
- Sync never deletes user-created tags or tag memberships outside the source
  tag.

## 9. Testing

Tests should be written before implementation.

Provider tests:

- Fake CCXT exchange markets normalize into crypto instruments.
- Inactive CCXT markets are skipped.
- A-share universe CSV rows normalize into equity instruments.

Store tests:

- `upsert_instrument` creates new records, updates changed records, and reports
  unchanged records.
- `ensure_tag` creates a missing tag and returns an existing tag without
  changing unrelated fields.

Service tests:

- `sync_source("bitget")` upserts instruments and creates the `Bitget` tag.
- A repeated sync reports unchanged or updated records instead of duplicate
  creation.
- Unknown source and unsupported provider errors are explicit.

HTTP tests:

- `GET /api/instrument-sources` returns provider metadata.
- `POST /api/instrument-sync/run` syncs instruments and source tag membership.
- Schedule create, list, enable, disable, run-now, delete, and runs endpoints
  return JSON payloads.
- Existing bearer-token authorization still protects the new routes.

Workbench tests:

- Rendered `/instruments` HTML includes the sync/source modal.
- The page calls `/api/instrument-sources`,
  `/api/instrument-sync/run`, and `/api/instrument-sync/schedules`.
- Manual sync reloads instruments and tags.

Browser verification:

- Start local data-source and workbench.
- Open `/instruments`.
- Confirm the sync modal lists Bitget and A-share.
- Run Bitget sync manually.
- Confirm instruments appear, the Bitget tag exists, pagination still works,
  and selected instruments still open the K-line page.

