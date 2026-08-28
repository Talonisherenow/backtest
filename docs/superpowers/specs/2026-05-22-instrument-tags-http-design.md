# Instrument Tags HTTP Design

## Scope

Add an HTTP-only instrument management capability to the existing data-source
service. The first version manages instrument basic information and user-defined
tags that can group multiple instruments, including watchlist-like tags. No CLI
commands are added.

## Goals

- Persist instrument records in SQLite metadata storage.
- Support instrument create, read, update, delete, list, and search through
  HTTP.
- Support user-defined tags, where one tag can contain multiple instruments and
  one instrument can belong to multiple tags.
- Reuse the existing data-source server authorization, JSON response style, and
  test patterns.

## Non-Goals

- No workbench UI changes in this iteration.
- No CLI commands for instrument or tag management.
- No automatic synchronization from AkShare or CCXT market metadata.
- No portfolio, strategy, or order behavior changes.

## Data Model

SQLite metadata storage gains three tables:

- `instruments`
  - `instrument_id` primary key, normalized uppercase where applicable.
  - `symbol`, `name`, `market`, `exchange`, `asset_class`, `quote_currency`.
  - `source_id` for optional data-source scoping.
  - `metadata_json` for provider-specific attributes.
  - `created_at`, `updated_at`.
- `instrument_tags`
  - `tag_id` primary key.
  - `name`, `description`, `color`.
  - `created_at`, `updated_at`.
  - `name` is unique to keep watchlist naming predictable.
- `instrument_tag_members`
  - `tag_id`, `instrument_id` composite primary key.
  - `created_at`.
  - Foreign keys cascade when an instrument or tag is deleted.

The service returns tags embedded in instrument list/detail payloads so clients
can render watchlist state without an extra request.

## HTTP API

Routes are added to `backtest.data_source.server` and delegate to
`DataSourceApi`.

- `GET /api/instruments`
  - Query: `source_id`, `q`, `tag`, `limit`, `offset`.
  - Returns `{ "instruments": [...], "total": N, "limit": N, "offset": N }`.
- `POST /api/instruments`
  - Creates or rejects duplicate instruments.
- `GET /api/instruments/{instrument_id}`
  - Returns one instrument with tags.
- `PATCH /api/instruments/{instrument_id}`
  - Updates mutable fields.
- `DELETE /api/instruments/{instrument_id}`
  - Deletes the instrument and tag memberships.
- `GET /api/instrument-tags`
  - Returns all tags with member counts.
- `POST /api/instrument-tags`
  - Creates a tag.
- `PATCH /api/instrument-tags/{tag_id}`
  - Updates tag metadata.
- `DELETE /api/instrument-tags/{tag_id}`
  - Deletes the tag and memberships.
- `PUT /api/instrument-tags/{tag_id}/members`
  - Replaces the full member set for one tag.
- `POST /api/instrument-tags/{tag_id}/members`
  - Adds one or more members.
- `DELETE /api/instrument-tags/{tag_id}/members/{instrument_id}`
  - Removes one member from a tag.

Errors use the existing server pattern: invalid user input raises `ValueError`
and becomes HTTP 400; unknown routes return 404; unexpected failures return 500.

## Architecture

Add a focused `backtest.data.instruments` module containing:

- Pydantic record/input models for instruments, tags, and paged results.
- `InstrumentStore`, which owns SQL operations and schema initialization
  through `MetadataStore`.

`MetadataStore._init_schema()` initializes the new tables next to catalog and
crawl task tables. `DataSourceApi` exposes thin methods that construct
`InstrumentStore` over a shared metadata path and JSON-serialize Pydantic
models using the existing `_jsonify()` helper.

The default store path is the first configured data source metadata path. If a
request provides `source_id`, the API uses that source's metadata path and also
stores the source id on created instruments unless explicitly provided.

## Validation

- Instrument ids and tag ids must be non-empty after trimming.
- `symbol`, `market`, `exchange`, `asset_class`, and `quote_currency` are
  optional enough to support crypto and equity records, but present values are
  normalized by trimming; instrument ids are uppercased.
- Tag names must be non-empty and unique.
- Tag membership updates require existing instruments and tags.
- Pagination clamps `limit` to a reasonable maximum.

## Testing

Tests cover:

- Store-level CRUD for instruments.
- Store-level tag CRUD and many-to-many membership replacement/add/remove.
- API JSON payloads for list/detail/search/tag filtering.
- HTTP server routes, including POST, PATCH, PUT, DELETE, and invalid input.
- Authorization remains enforced by the existing server wrapper.

