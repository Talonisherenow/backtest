# Instrument Workbench Page Design

## Scope

Add a simple workbench UI for the HTTP-only instrument and tag/list API. The
chosen layout is option C from the visual companion: a lightweight home overview
plus a dedicated instrument management page.

## Goals

- Show instrument/list visibility on the workbench home.
- Add a new `/instruments` workbench route.
- Let users see all instruments and tag/list groupings in one page.
- Keep the first UI simple and read-heavy, with enough controls to create,
  update, and organize instruments without using CLI commands.

## Non-Goals

- No new backend API routes beyond the existing instrument HTTP API.
- No CLI commands.
- No advanced batch import, universe sync, or strategy integration.
- No chart or K-line behavior changes.

## Home Layout

The workbench home keeps the existing Strategy Results and K-line entries. It
adds an `Instrument Lists` entry and, when a data API base URL is configured,
shows compact instrument summary tiles:

- instrument count
- tag/list count
- first few list names with member counts

When the data API is unavailable, the page still renders the static navigation
entry and shows an offline state for the summary.

## Instrument Page Layout

`/instruments` uses a three-zone operational layout:

- Top summary band with counts, active source, and quick actions.
- Left list panel for tags/watchlists and member counts.
- Main table for instruments with search/source/tag filters.
- Right details panel for selected instrument metadata and tag membership.

The page uses the existing workbench data API helpers and Bearer token handling.
It fetches:

- `GET /api/data-sources`
- `GET /api/instruments`
- `GET /api/instrument-tags`

Mutations use the existing API:

- `POST /api/instruments`
- `PATCH /api/instruments/{instrument_id}`
- `DELETE /api/instruments/{instrument_id}`
- `POST /api/instrument-tags`
- `PATCH /api/instrument-tags/{tag_id}`
- `DELETE /api/instrument-tags/{tag_id}`
- `POST /api/instrument-tags/{tag_id}/members`
- `DELETE /api/instrument-tags/{tag_id}/members/{instrument_id}`

## Error Handling

The UI shows inline load or mutation errors without blocking navigation to other
workbench pages. Empty states distinguish no configured data API, no instruments,
and no tags.

## Testing

Tests should cover:

- Home HTML includes the Instruments entry and summary JavaScript.
- Workbench server serves `/instruments`.
- Instrument page HTML includes data API fetches and mutation routes.
- Focused chart/workbench tests still pass.

