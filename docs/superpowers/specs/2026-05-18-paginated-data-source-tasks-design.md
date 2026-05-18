# Paginated Data Source Tasks Design

Date: 2026-05-18
Status: proposed for implementation planning
Branch: `feat/data-crawl-management`

## 1. Background

The workbench home page currently embeds a read-only data-source monitor. When a
remote data-source API is configured, the browser polls:

```text
GET /api/data-sources
GET /api/data/tasks?source_id=<source_id>
GET /api/data/jobs
```

The current task route returns every crawl task for a source. This is acceptable
for small local experiments, but it will not scale once data crawling becomes a
daily operational workflow with many symbols, frequencies, retries, and
historical backfills.

The desired behavior is:

- keep the workbench home summary lightweight and visually unchanged
- move task details into a paginated drawer
- let users inspect tasks by source tab
- support symbol search plus multi-select frequency and status filters

## 2. Goals

- Add server-side pagination for crawl tasks.
- Add server-side filtering by symbol, frequency, and status.
- Keep the workbench home monitor summary close to the current visual behavior.
- Avoid pulling all task rows into the browser for summary counts or task
  browsing.
- Preserve the existing read-only scope. The workbench should not submit,
  retry, cancel, or mutate crawl tasks in this phase.
- Keep the first implementation compatible with the current stdlib HTTP server
  and vanilla JavaScript workbench shell.

## 3. Non-Goals

- No task mutation from the workbench.
- No full-text search across `last_error`.
- No advanced query builder.
- No persisted user preferences for filters, page size, or active tab.
- No WebSocket or SSE stream.
- No cross-source global task table as the primary view.
- No change to the `DataSyncService` crawling behavior.

## 4. UX

### 4.1 Workbench Home Summary

The compact `Data Source` strip remains in the same location below the
workbench header and above the navigation cards.

It still shows one pill per source:

- source label
- active task count, combining `pending`, `running`, and `retrying`
- failed task count when present
- success count
- last refresh time

The visual language should remain unchanged: failed sources get the red
treatment, active sources get the blue treatment, idle/successful sources stay
quiet.

The difference is data flow: summary counts come from a lightweight summary
endpoint instead of from full task lists.

### 4.2 Details Drawer

The `Details` button opens the existing right-side drawer. Inside the drawer:

- source tabs appear at the top, one tab per configured source
- each tab has independent pagination and filter state
- the selected source's task list is fetched from the server

Default state:

- active tab: first source returned by `/api/data-sources`
- page: `1`
- page size: `50`
- symbol query: empty
- frequencies: all
- statuses: all
- ordering: `updated_at desc`

### 4.3 Filters

Each source tab supports:

- `symbol`: text search with partial matching
- `frequency`: multi-select
- `status`: multi-select

`last_error` stays visible in the table but is not searchable.

The browser should debounce symbol search before requesting a new page. A 300 ms
debounce is enough for this UI.

Frequency and status filter options should be derived from the server summary
for the selected source. This avoids hard-coded crypto/A-share assumptions in
the browser.

### 4.4 Task Table

The drawer table keeps the existing read-only columns:

- source
- symbol
- frequency
- adjust
- status
- attempts
- updated time
- last error

Rows should be stable and dense. The table should not resize the drawer when
filters or pages change.

Pagination controls live below the table:

- previous page
- next page
- current page / total pages
- total matching tasks
- page size selector: `25`, `50`, `100`

When filters change, the page resets to `1`.

## 5. API

### 5.1 Task Summary

Add:

```text
GET /api/data/tasks/summary?source_id=bitget
```

Response:

```json
{
  "source_id": "bitget",
  "total": 1234,
  "status_counts": {
    "success": 1200,
    "failed": 10,
    "running": 2,
    "pending": 22
  },
  "frequency_counts": {
    "1d": 200,
    "4h": 200
  },
  "latest_updated_at": "2026-05-18T02:52:00+00:00"
}
```

Notes:

- Missing statuses or frequencies can be omitted from count maps.
- `latest_updated_at` is `null` when a source has no tasks.
- The summary is source-scoped because each source maps to its own metadata DB.

### 5.2 Paginated Tasks

Extend the existing route:

```text
GET /api/data/tasks?source_id=bitget&page=1&page_size=50&symbol=BTC&frequency=1d&frequency=4h&status=failed&status=running
```

Response:

```json
{
  "source_id": "bitget",
  "tasks": [],
  "page": 1,
  "page_size": 50,
  "total": 1234,
  "total_pages": 25,
  "filters": {
    "symbol": "BTC",
    "frequencies": ["1d", "4h"],
    "statuses": ["failed", "running"]
  }
}
```

Rules:

- `page` defaults to `1`.
- `page_size` defaults to `50`.
- `page_size` is capped at `100`.
- `symbol` performs case-insensitive partial matching.
- repeated `frequency` params form an OR filter.
- repeated `status` params form an OR filter.
- sort order is `updated_at desc, task_id desc`.
- invalid pagination values return `400`.

### 5.3 Jobs

The existing in-process `/api/data/jobs` route can stay unchanged in this phase.
It is not expected to grow the same way persistent crawl tasks grow. The home
summary can continue to fetch it as a small optional add-on, or the UI can show
job count only when the response is cheap.

## 6. Backend Design

Add query methods to `CrawlTaskManager`:

```python
def task_summary(self) -> CrawlTaskSummary: ...

def list_tasks_page(
    self,
    *,
    page: int = 1,
    page_size: int = 50,
    symbol: str | None = None,
    frequencies: list[Frequency] | None = None,
    statuses: list[str] | None = None,
) -> CrawlTaskPage: ...
```

The implementation should use SQL `COUNT`, `GROUP BY`, `LIMIT`, and `OFFSET`.
It should not call `list_tasks()` and slice in Python.

Recommended internal query construction:

- build a small list of SQL predicates
- bind all user inputs as parameters
- use `LOWER(symbol) LIKE ?` for symbol search
- use `IN (?, ?, ...)` for frequency and status filters

The existing `list_tasks()` should remain for CLI compatibility and tests.

`DataSourceApi.tasks()` should accept pagination/filter arguments and serialize
the page object. `DataSourceApi.task_summary()` should expose the summary object.

`backtest.data_source.server` should parse:

- required `source_id`
- optional integer `page`
- optional integer `page_size`
- optional `symbol`
- repeated `frequency`
- repeated `status`

## 7. Frontend Design

`render_workbench_index_html()` remains a static HTML shell with embedded
vanilla JavaScript.

State shape:

```js
let dataMonitorState = {
  sources: [],
  summariesBySource: {},
  jobs: [],
  selectedSourceId: "",
  taskPagesBySource: {},
  filtersBySource: {},
  lastUpdated: "",
  error: "",
};
```

Home refresh flow:

1. Fetch `/api/data-sources`.
2. For each source, fetch `/api/data/tasks/summary?source_id=...`.
3. Optionally fetch `/api/data/jobs`.
4. Render source pills from summaries.

Drawer flow:

1. Open drawer.
2. Ensure active source tab is selected.
3. Fetch the active source page with current filters.
4. Render table and pagination controls.

Periodic refresh:

- keep the existing 10 second monitor refresh while visible
- refresh summaries on the timer
- refresh the open drawer's active page only when the drawer is open

## 8. Compatibility

The first implementation can keep `/api/data/tasks?source_id=<id>` compatible by
returning a page envelope instead of a raw full list only if all callers are
updated in the same change.

Because current workbench code is the primary HTTP consumer, prefer moving to
the page envelope now and updating tests accordingly.

CLI `backtest data tasks` continues to use `CrawlTaskManager.list_tasks()` and
is not affected.

## 9. Testing

Backend tests:

- `CrawlTaskManager.task_summary()` returns total, status counts, frequency
  counts, and latest update timestamp.
- `CrawlTaskManager.list_tasks_page()` paginates by `updated_at desc`.
- symbol search is case-insensitive and partial.
- frequency and status multi-select filters are OR filters.
- page size cap is enforced.
- `/api/data/tasks/summary` returns serialized summary.
- `/api/data/tasks` parses repeated `frequency` and `status` query params.

Workbench tests:

- home shell fetches task summaries instead of full task lists for the monitor
  strip.
- drawer markup contains source tabs, symbol search, frequency multi-select,
  status multi-select, and pagination controls.
- JS includes paginated task URL construction with repeated query params.
- strategy results page remains free of the data-source monitor.

## 10. Rollout

1. Add backend pagination and summary methods behind tests.
2. Add HTTP route and query parsing.
3. Update workbench home monitor to use summaries.
4. Update drawer to source tabs, filters, and pagination.
5. Run focused tests for data source and workbench server.
6. Manually verify with a local data-source service containing both Bitget and
   A-share metadata.

## 11. Open Questions

Resolved:

- Source switching should be source tabs, not a global mixed table.
- `frequency` and `status` should be multi-select filters.
- `last_error` should remain display-only.

Remaining:

- Whether the job snapshot list should eventually become persistent and
  paginated. This is out of scope for this task because current jobs are
  in-process snapshots and not the long-lived crawl-task table.
