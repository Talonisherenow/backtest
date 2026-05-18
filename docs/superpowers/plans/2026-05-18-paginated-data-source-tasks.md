# Paginated Data Source Tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Keep the workbench data-source monitor read-only.

**Goal:** Make the workbench data-source task drawer scalable by adding source-tabbed task browsing, server-side pagination, symbol search, and multi-select frequency/status filters, while preserving the existing workbench home summary behavior.

**Design Spec:** `docs/superpowers/specs/2026-05-18-paginated-data-source-tasks-design.md`

**Architecture:** Extend `CrawlTaskManager` with SQL-backed task summary and paginated query methods. Expose those through `DataSourceApi` and `backtest.data_source.server`. Update the workbench home HTML/JavaScript so the compact summary uses lightweight summary calls, and the drawer fetches a paginated page only for the selected source tab.

**Tech Stack:** Python 3.11+, stdlib `http.server`, SQLite metadata store, Pydantic crawl task records, pytest, vanilla HTML/CSS/JavaScript in `backtest/charts/workbench_server.py`.

---

## File Structure

- Modify `backtest/data/tasks.py`: add SQL-backed summary and paginated task query methods.
- Modify `backtest/data_source/api.py`: expose `task_summary()` and paginated `tasks()`.
- Modify `backtest/data_source/server.py`: parse task summary routes and repeated filter query parameters.
- Modify `backtest/charts/workbench_server.py`: update workbench monitor shell, drawer controls, source tabs, filters, and pagination.
- Modify `tests/data/test_tasks.py`: cover task summary and paginated task queries.
- Modify `tests/data_source/test_api.py`: cover serialized summary and paginated task payloads.
- Modify `tests/data_source/test_server.py`: cover HTTP route parsing for summaries, pagination, repeated `frequency`, and repeated `status`.
- Modify `tests/charts/test_workbench_server.py`: cover updated workbench shell fetch wiring and drawer controls.

## Task 1: Task Query Models And Manager Methods

**Files:**

- Modify: `backtest/data/tasks.py`
- Modify: `tests/data/test_tasks.py`

- [ ] **Step 1: Add failing task manager tests**

Add tests for:

- summary count totals and group counts by `status`
- summary group counts by `frequency`
- latest update timestamp
- first page returns newest updated tasks first
- second page returns the next slice
- symbol search is case-insensitive and partial
- repeated frequency/status filters behave as OR filters
- page size cap is enforced

Suggested test names:

```python
def test_task_manager_summarizes_tasks_by_status_and_frequency(tmp_path: Path):
    ...

def test_task_manager_lists_paginated_tasks_with_symbol_frequency_and_status_filters(tmp_path: Path):
    ...
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
uv run --with pytest python -m pytest tests/data/test_tasks.py -q
```

Expected: FAIL because `task_summary()` and `list_tasks_page()` do not exist.

- [ ] **Step 3: Implement task query models**

Add small dataclasses in `backtest/data/tasks.py`:

```python
@dataclass(frozen=True)
class CrawlTaskSummary:
    total: int
    status_counts: dict[str, int]
    frequency_counts: dict[str, int]
    latest_updated_at: datetime | None


@dataclass(frozen=True)
class CrawlTaskPage:
    tasks: list[CrawlTaskRecord]
    page: int
    page_size: int
    total: int
    total_pages: int
```

- [ ] **Step 4: Implement SQL-backed summary**

Use SQL queries against `crawl_tasks`:

```sql
SELECT COUNT(*) AS total, MAX(updated_at) AS latest_updated_at FROM crawl_tasks
SELECT status, COUNT(*) AS count FROM crawl_tasks GROUP BY status
SELECT frequency, COUNT(*) AS count FROM crawl_tasks GROUP BY frequency
```

Parse `latest_updated_at` with the existing `_record_from_row` datetime parsing
style.

- [ ] **Step 5: Implement SQL-backed page query**

Implement:

```python
def list_tasks_page(
    self,
    *,
    page: int = 1,
    page_size: int = 50,
    symbol: str | None = None,
    frequencies: list[Frequency] | None = None,
    statuses: list[str] | None = None,
) -> CrawlTaskPage:
    ...
```

Rules:

- reject `page < 1`
- reject `page_size < 1`
- cap `page_size` at `100`
- use `LOWER(symbol) LIKE ?`
- use `IN (...)` for frequencies and statuses
- order by `updated_at DESC, task_id DESC`
- compute `total_pages = max(1, ceil(total / page_size))`

- [ ] **Step 6: Run tests and verify GREEN**

Run:

```bash
uv run --with pytest python -m pytest tests/data/test_tasks.py -q
```

## Task 2: Data Source API Facade

**Files:**

- Modify: `backtest/data_source/api.py`
- Modify: `tests/data_source/test_api.py`

- [ ] **Step 1: Add failing API tests**

Add coverage for:

- `api.task_summary("a_share")`
- `api.tasks("a_share", page=1, page_size=1, symbol="000001", frequencies=["1d"], statuses=["failed"])`
- serialized task page envelope contains `page`, `page_size`, `total`, `total_pages`, and `filters`

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source/test_api.py -q
```

- [ ] **Step 3: Implement `DataSourceApi.task_summary()`**

Add:

```python
def task_summary(self, source_id: str) -> dict[str, Any]:
    spec = self.config.source(source_id)
    summary = self._tasks(spec).task_summary()
    return {
        "source_id": source_id,
        "total": summary.total,
        "status_counts": summary.status_counts,
        "frequency_counts": summary.frequency_counts,
        "latest_updated_at": summary.latest_updated_at.isoformat() if summary.latest_updated_at else None,
    }
```

- [ ] **Step 4: Extend `DataSourceApi.tasks()`**

Change it to accept:

```python
def tasks(
    self,
    source_id: str,
    *,
    page: int = 1,
    page_size: int = 50,
    symbol: str | None = None,
    frequencies: list[str] | None = None,
    statuses: list[str] | None = None,
) -> dict[str, Any]:
    ...
```

Convert frequency strings to `Frequency` values before passing to
`CrawlTaskManager`.

Return a page envelope:

```json
{
  "source_id": "a_share",
  "tasks": [],
  "page": 1,
  "page_size": 50,
  "total": 0,
  "total_pages": 1,
  "filters": {
    "symbol": "",
    "frequencies": [],
    "statuses": []
  }
}
```

- [ ] **Step 5: Run API tests**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source/test_api.py -q
```

## Task 3: HTTP Routes And Query Parsing

**Files:**

- Modify: `backtest/data_source/server.py`
- Modify: `tests/data_source/test_server.py`

- [ ] **Step 1: Add failing server tests**

Add coverage for:

- `GET /api/data/tasks/summary?source_id=a_share`
- `GET /api/data/tasks?source_id=a_share&page=1&page_size=1&symbol=000001`
- repeated query params:

```text
frequency=1d&frequency=4h&status=failed&status=running
```

- invalid pagination returns `400`

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source/test_server.py -q
```

- [ ] **Step 3: Add summary route**

In `do_GET`, route before the existing tasks route:

```python
elif parsed.path == "/api/data/tasks/summary":
    self._send_json(200, api.task_summary(self._required(query, "source_id")))
```

- [ ] **Step 4: Parse task list args**

Add helper:

```python
def _task_args(self, query: dict[str, list[str]]) -> dict[str, Any]:
    ...
```

It should parse:

- `source_id`
- `page`
- `page_size`
- `symbol`
- repeated `frequency`
- repeated `status`

Use `query.get("frequency", [])` and `query.get("status", [])`.

- [ ] **Step 5: Run server tests**

Run:

```bash
uv run --with pytest python -m pytest tests/data_source/test_server.py -q
```

## Task 4: Workbench Home Summary Flow

**Files:**

- Modify: `backtest/charts/workbench_server.py`
- Modify: `tests/charts/test_workbench_server.py`

- [ ] **Step 1: Add failing shell test for summary calls**

Update `test_render_workbench_index_html_hosts_readonly_data_source_monitor` so
it expects:

```js
fetch(dataApiUrl(`/api/data/tasks/summary?source_id=${encodeURIComponent(source.source_id)}`), dataApiRequestOptions())
```

and no longer expects the old full-task summary fetch for the home strip.

- [ ] **Step 2: Add failing shell test for drawer controls**

Assert the rendered shell includes:

- `id="dataSourceTabs"`
- `id="taskSymbolSearch"`
- `id="taskFrequencyFilters"`
- `id="taskStatusFilters"`
- `id="taskPreviousPageButton"`
- `id="taskNextPageButton"`
- `id="taskPageSizeSelect"`

- [ ] **Step 3: Run workbench tests and verify RED**

Run:

```bash
uv run --with pytest python -m pytest tests/charts/test_workbench_server.py -q
```

- [ ] **Step 4: Update monitor state and summary loading**

Change browser state from `tasksBySource` to summary-first:

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

Update `loadDataMonitor()`:

1. fetch sources
2. fetch task summaries for each source
3. fetch jobs as optional small data
4. render source pills from summary counts

- [ ] **Step 5: Preserve existing visual summary**

Keep `renderDataMonitor()` pill text equivalent to the old behavior:

- active count from pending/running/retrying
- failed count
- success count

Use `summary.status_counts`.

- [ ] **Step 6: Run workbench tests**

Run:

```bash
uv run --with pytest python -m pytest tests/charts/test_workbench_server.py -q
```

## Task 5: Source Tabs, Filters, And Pagination UI

**Files:**

- Modify: `backtest/charts/workbench_server.py`
- Modify: `tests/charts/test_workbench_server.py`

- [ ] **Step 1: Add drawer markup**

Inside the drawer, add:

- tab row: `dataSourceTabs`
- filters row:
  - symbol search input
  - frequency checkbox group
  - status checkbox group
  - page size select
- pagination row:
  - previous button
  - page meta
  - next button

Keep the table columns unchanged.

- [ ] **Step 2: Implement per-source filter state**

Add helpers:

```js
function defaultTaskFilters() { ... }
function filtersForSource(sourceId) { ... }
function setSelectedSource(sourceId) { ... }
```

Each source gets independent:

- `symbol`
- `frequencies`
- `statuses`
- `page`
- `pageSize`

- [ ] **Step 3: Build task page URL**

Add:

```js
function taskPageUrl(sourceId, filters) { ... }
```

Use `URLSearchParams` and repeated `append()` calls for `frequency` and
`status`.

- [ ] **Step 4: Fetch selected source page**

Add:

```js
async function loadSelectedTaskPage() { ... }
```

Fetch only the selected source's current page. Store the page payload in
`taskPagesBySource[sourceId]`.

- [ ] **Step 5: Render tabs and controls**

Render one tab per source. Clicking a tab:

1. sets `selectedSourceId`
2. renders controls from that source's summary
3. loads that source's current page

Frequency options come from `summary.frequency_counts` keys.

Status options come from `summary.status_counts` keys.

- [ ] **Step 6: Render task drawer from page payload**

Change `renderTaskDrawer()` to use only the selected source's page payload.

Drawer meta should show:

```text
<total> matching tasks · page <page>/<total_pages>
```

For empty pages, show `No matching crawl tasks`.

- [ ] **Step 7: Wire interactions**

Add listeners:

- symbol input: debounce 300 ms, reset page to 1, load selected page
- frequency checkbox: reset page to 1, load selected page
- status checkbox: reset page to 1, load selected page
- previous/next: adjust page and load selected page
- page size select: update page size, reset page to 1, load selected page

- [ ] **Step 8: Refresh behavior**

Keep periodic summary refresh every 10 seconds when visible. If drawer is open,
also refresh the selected source's current page.

- [ ] **Step 9: Run workbench tests**

Run:

```bash
uv run --with pytest python -m pytest tests/charts/test_workbench_server.py -q
```

## Task 6: Focused Regression Suite

**Files:**

- No new files unless a test reveals a gap.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run --with pytest python -m pytest \
  tests/data/test_tasks.py \
  tests/data_source/test_api.py \
  tests/data_source/test_server.py \
  tests/charts/test_workbench_server.py \
  -q
```

- [ ] **Step 2: Fix regressions**

Fix any failing focused tests without changing unrelated behavior.

- [ ] **Step 3: Optional broader check**

If time allows, run:

```bash
uv run --with pytest python -m pytest tests/data_source tests/charts/test_workbench_server.py -q
```

## Task 7: Manual Verification

**Files:**

- No code changes expected.

- [ ] **Step 1: Start or reuse data-source service**

Use the current local data-source service:

```bash
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" \
  http://127.0.0.1:8768/api/health
```

- [ ] **Step 2: Verify summary API**

```bash
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" \
  "http://127.0.0.1:8768/api/data/tasks/summary?source_id=bitget"
```

- [ ] **Step 3: Verify paginated task API**

```bash
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" \
  "http://127.0.0.1:8768/api/data/tasks?source_id=bitget&page=1&page_size=25&symbol=BTC&frequency=1d&status=success"
```

- [ ] **Step 4: Open workbench**

Start or reuse workbench pointed at the data-source API. Verify:

- home summary still appears in the same place
- source tabs appear in the drawer
- symbol search filters rows
- frequency/status multi-select filters rows
- pagination buttons move between pages
- K-line and strategy results links still work

## Implementation Notes

- Do not use Python-side slicing of `list_tasks()` for the new API.
- Do not add task mutation controls to the workbench.
- Keep page-size controls bounded to avoid accidental large responses.
- Keep old CLI behavior intact.
- Use repeated query params for multi-select filters rather than comma-separated strings.
