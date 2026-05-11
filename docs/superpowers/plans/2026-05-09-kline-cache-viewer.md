# K-line Cache Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone K-line cache viewer that discovers cached symbols and frequencies from local Parquet files and renders a single portable HTML page.

**Architecture:** Extend `backtest.charts.kline_viewer` so the payload model contains per-symbol series for each cached frequency. Keep the existing top-level `symbols` payload shape backward-compatible, while making the HTML render from `item.series`. Extend `backtest chart viewer` with frequency and adjust options.

**Tech Stack:** Python 3.11, pandas, pyarrow-backed Parquet, Typer CLI, Plotly in generated static HTML, pytest.

---

## File Structure

- Modify `backtest/charts/kline_viewer.py`: cache discovery, series payload construction, timestamp formatting, and HTML template.
- Modify `backtest/cli/chart.py`: CLI options for repeatable `--frequency` and `--adjust`.
- Modify `tests/charts/test_kline_viewer.py`: payload and HTML assertions.
- Modify `tests/test_cli_commands.py`: chart CLI option wiring test.

## Task 1: Multi-Frequency Cache Payload

**Files:**
- Modify: `tests/charts/test_kline_viewer.py`
- Modify: `backtest/charts/kline_viewer.py`

- [ ] **Step 1: Write failing payload tests**

Add tests that create `BTC/USDT` cache partitions for `1d` and `4h`, call `build_kline_payload(..., frequency=None, adjust="none")`, and assert:

```python
payload = build_kline_payload(bars_root, symbols=["BTC/USDT"], limit=2, frequency=None, adjust="none")
item = payload["symbols"][0]
assert item["symbol"] == "BTC/USDT"
assert [series["frequency"] for series in item["series"]] == ["4h", "1d"]
assert item["series"][0]["bars"][-1]["date"] == "2025-01-02T08:00:00"
assert item["series"][1]["rows"] == 3
assert item["series"][1]["years"] == [2025]
```

Also add a filter test:

```python
payload = build_kline_payload(bars_root, symbols=["BTC/USDT"], limit=2, frequency="4h", adjust="none")
assert [series["frequency"] for series in payload["symbols"][0]["series"]] == ["4h"]
```

- [ ] **Step 2: Run tests to verify RED**

Run: `pytest tests/charts/test_kline_viewer.py -q`

Expected: FAIL because `frequency=None` is not handled, crypto partition paths are not decoded, and payload items do not include `series`.

- [ ] **Step 3: Implement series payload**

In `backtest/charts/kline_viewer.py`:

```python
from backtest.core.symbols import normalize_symbol, safe_symbol_path, symbol_from_safe_path
```

Update `build_kline_payload` to accept `frequency: str | None = "1d"` and optional `frequencies: list[str] | None = None`. Resolve frequencies as:

```python
selected_frequencies = frequencies or ([frequency] if frequency else _discover_frequencies(bars_root, adjust))
```

Build each item with:

```python
series = []
for current_frequency in selected_frequencies:
    entry = _read_symbol_series(bars_root, symbol, current_frequency, adjust, limit)
    if entry is not None:
        series.append(entry)
```

Keep compatibility fields:

```python
"bars": series[0]["bars"],
"series": series,
```

Use `safe_symbol_path(symbol)` when reading symbol directories, and `symbol_from_safe_path(...)` when discovering symbols from path segments.

Create `_read_symbol_series(...)` that returns:

```python
{
    "frequency": frequency,
    "adjust": adjust,
    "rows": int(len(frame)),
    "first_bar": _timestamp_label(frame["date"].iloc[0], frequency),
    "last_bar": _timestamp_label(frame["date"].iloc[-1], frequency),
    "years": sorted(int(path.parent.name.removeprefix("year=")) for path in paths),
    "bars": [_bar_to_json(row, frequency) for _, row in limited[BAR_COLUMNS].iterrows()],
}
```

- [ ] **Step 4: Run tests to verify GREEN**

Run: `pytest tests/charts/test_kline_viewer.py -q`

Expected: PASS.

## Task 2: Static HTML UI For Frequency Switching And Data Drawer

**Files:**
- Modify: `tests/charts/test_kline_viewer.py`
- Modify: `backtest/charts/kline_viewer.py`

- [ ] **Step 1: Write failing HTML test assertions**

In `test_write_kline_viewer_embeds_payload_for_file_url_usage`, add a `series` field to the sample symbol and assert:

```python
assert "frequencyButtons" in html
assert "dataStatusDrawer" in html
assert "toggleDataStatus" in html
assert "seriesByFrequency" in html
```

- [ ] **Step 2: Run HTML test to verify RED**

Run: `pytest tests/charts/test_kline_viewer.py::test_write_kline_viewer_embeds_payload_for_file_url_usage -q`

Expected: FAIL because the current HTML template does not include these UI hooks.

- [ ] **Step 3: Implement HTML behavior**

Update `HTML_TEMPLATE` so client-side state includes:

```javascript
const state = {
  symbol: symbols[0]?.symbol || "",
  frequency: symbols[0]?.series?.[0]?.frequency || payload.frequency || "1d",
  board: "all",
  search: "",
  range: "300",
  drawerOpen: false,
};
```

Add a frequency segmented control with id `frequencyButtons`, a `Data Status` button that calls `toggleDataStatus`, and an aside with id `dataStatusDrawer`.

Render functions should use:

```javascript
function seriesByFrequency(item) {
  return new Map((item.series || [{ frequency: payload.frequency, bars: item.bars || [] }]).map((series) => [series.frequency, series]));
}
```

Chart rendering should select the current series, range its `bars`, and update the summary with `series.rows`, `series.first_bar`, and `series.last_bar`.

The drawer should list each visible symbol and frequency row; clicking a row should set `state.symbol`, `state.frequency`, repopulate controls, close the drawer, and render.

- [ ] **Step 4: Run chart tests to verify GREEN**

Run: `pytest tests/charts/test_kline_viewer.py -q`

Expected: PASS.

## Task 3: CLI Wiring

**Files:**
- Modify: `tests/test_cli_commands.py`
- Modify: `backtest/cli/chart.py`

- [ ] **Step 1: Write failing CLI test**

Add a test that monkeypatches `backtest.cli.chart.build_kline_payload` and invokes:

```python
result = CliRunner().invoke(
    app,
    [
        "chart",
        "viewer",
        "--bars-root",
        str(bars_root),
        "--output",
        str(output_path),
        "--frequency",
        "1d",
        "--frequency",
        "4h",
        "--adjust",
        "none",
    ],
)
```

Assert:

```python
assert captured["frequencies"] == ["1d", "4h"]
assert captured["adjust"] == "none"
```

- [ ] **Step 2: Run CLI test to verify RED**

Run: `pytest tests/test_cli_commands.py::test_chart_viewer_cli_passes_frequency_and_adjust_options -q`

Expected: FAIL because `--frequency` and `--adjust` are not accepted.

- [ ] **Step 3: Implement CLI options**

In `backtest/cli/chart.py`, add:

```python
frequency: list[str] | None = typer.Option(None, "--frequency", help="Optional frequency filter; repeat for multiple frequencies"),
adjust: str = typer.Option("qfq", "--adjust", help="Adjust mode to read from cache"),
```

Call:

```python
payload = build_kline_payload(
    bars_root=bars_root,
    universe_path=universe_path,
    symbols=selected_symbols or None,
    limit=limit,
    frequency=None if not frequency else frequency[0],
    frequencies=list(frequency or []) or None,
    adjust=adjust,
)
```

- [ ] **Step 4: Run CLI test to verify GREEN**

Run: `pytest tests/test_cli_commands.py::test_chart_viewer_cli_passes_frequency_and_adjust_options -q`

Expected: PASS.

## Task 4: End-To-End Verification

**Files:**
- Modify only if verification reveals a defect in prior files.

- [ ] **Step 1: Run focused tests**

Run: `pytest tests/charts/test_kline_viewer.py tests/test_cli_commands.py -q`

Expected: PASS.

- [ ] **Step 2: Generate crypto viewer from local cache**

Run:

```bash
.venv/bin/backtest chart viewer \
  --bars-root data/crypto/bars \
  --adjust none \
  --output runs/charts/crypto_kline_viewer.html \
  --limit 300
```

Expected: command exits 0 and reports a viewer for cached crypto symbols.

- [ ] **Step 3: Smoke-check generated HTML**

Run:

```bash
rg -n "BTC/USDT|frequencyButtons|dataStatusDrawer|Plotly.newPlot" runs/charts/crypto_kline_viewer.html
```

Expected: all strings are present.

- [ ] **Step 4: Run full test suite**

Run: `pytest -q`

Expected: PASS.
