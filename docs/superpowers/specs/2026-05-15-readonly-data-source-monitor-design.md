# Read-Only Data Source Monitor Design

## Goal

Show the current crawl-task state on the workbench home page without turning the workbench into a task-control console.

## Scope

The first version is read-only. It does not submit crawl jobs, retry failed tasks, cancel jobs, or edit data-source configuration. Those actions stay outside the workbench and can be handled later through IM or other control surfaces.

## UX

Add a compact `Data Source` monitor strip below the workbench home header and above the cards that link to `Strategy Results` and `K-line Viewer`.

The strip shows one pill per source:

- source label
- active task count, combining `pending`, `running`, and `retrying`
- failed task count when present
- success count
- last refresh time

A `Details` button opens a right-side drawer. The drawer shows a task table with:

- source
- symbol
- frequency
- adjust
- status
- attempts
- updated time
- last error

Failed tasks are visually emphasized. Active tasks get a blue status treatment. Successful tasks get a green status treatment.

## Data Flow

The workbench home shell receives `data_api_base_url` from `serve_chart_workbench` when the workbench is started with `--data-api-base-url`.

The browser reads these data-source API routes directly:

- `GET /api/data-sources`
- `GET /api/data/tasks?source_id=<source_id>`
- `GET /api/data/jobs`

The strategy results page remains focused on backtest result browsing and does not render the data-source monitor.

## Refresh And Failure Behavior

The monitor refreshes every 10 seconds while the page is visible. It pauses while the browser tab is hidden and refreshes again when visible.

If the data-source API cannot be reached, the monitor remains visible and shows an offline pill with the last checked time. The workbench navigation remains usable.

## Testing

Tests should cover:

- the workbench home shell renders the monitor markup and data-source fetch wiring
- `serve_chart_workbench` passes `data_api_base_url` into the workbench home shell
- the strategy-results shell does not render the data-source monitor
- existing strategy-results and workbench tests continue to pass
