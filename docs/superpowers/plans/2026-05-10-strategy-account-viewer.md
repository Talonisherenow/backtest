# Strategy Account Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone strategy account viewer for one backtest case, showing position market values, account cash/equity, strategy return, and the full order list.

**Architecture:** Add a focused chart module that converts `orders + bars + equity_curve` into a browser-ready payload and static Plotly HTML. Keep it separate from the single-symbol order K-line viewer so single-instrument and account-level semantics do not mix. Reconstruct position market values from orders for the current aggregate run output, while documenting that future exports should provide positions directly.

**Status:** Implemented in the current feature branch. The generated example artifact is `runs/charts/strategy_account_viewer_signal_02_hold_20.html`.

**Tech Stack:** Python 3.11+, pandas, Plotly in static HTML, pytest via `uv run pytest`.

---

## File Structure

Create:

- `backtest/charts/strategy_account_viewer.py`
  - Build the account-level viewer payload.
  - Reconstruct per-symbol market value curves from filled/adjusted orders and bars.
  - Render a static Plotly HTML page.
  - Write the HTML artifact.
- `tests/charts/test_strategy_account_viewer.py`
  - Test position market value reconstruction.
  - Test account return curve construction.
  - Test HTML contains the required account-level sections.

Modify:

- `backtest/charts/__init__.py`
  - Export `build_strategy_account_payload` and `write_strategy_account_viewer`.

Already created before implementation:

- `docs/superpowers/specs/2026-05-10-strategy-account-viewer-design.md`
- `docs/superpowers/plans/2026-05-10-strategy-account-viewer.md`

Out of scope:

- Adding a CLI command.
- Changing the single-symbol order K-line viewer.
- Changing backtest execution logic.
- Exporting `positions.csv` from the aggregate run.

## Task 1: Lock The Payload Contract

**Files:**
- Create: `tests/charts/test_strategy_account_viewer.py`
- Create: `backtest/charts/strategy_account_viewer.py`

- [ ] **Step 1: Write failing payload test**

Create a test with two symbols, three dates, orders, bars, and an account equity curve:

```python
def test_build_strategy_account_payload_reconstructs_position_values():
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-02", "2025-01-03", "2025-01-03", "2025-01-06", "2025-01-06"]),
            "symbol": ["000001.SZ", "600000.SH", "000001.SZ", "600000.SH", "000001.SZ", "600000.SH"],
            "close": [10.5, 20.0, 11.0, 21.0, 12.0, 22.0],
        }
    )
    orders = pd.DataFrame(
        {
            "case_id": ["case_a", "case_a", "case_a", "case_b"],
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-02"]),
            "symbol": ["000001.SZ", "600000.SH", "000001.SZ", "000001.SZ"],
            "side": ["buy", "buy", "sell", "buy"],
            "filled_shares": [100, 50, 40, 999],
            "price": [10.2, 20.8, 12.1, 10.0],
            "commission": [1.0, 1.0, 1.0, 1.0],
            "tax": [0.0, 0.0, 0.5, 0.0],
            "transfer_fee": [0.1, 0.1, 0.1, 0.1],
            "slippage_cost": [0.0, 0.0, 0.0, 0.0],
            "status": ["filled", "filled", "filled", "filled"],
            "reason": ["", "", "", ""],
        }
    )
    equity = pd.DataFrame(
        {
            "case_id": ["case_a", "case_a", "case_a"],
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            "equity": [100000.0, 101000.0, 103000.0],
            "cash": [98900.0, 97800.0, 98200.0],
        }
    )

    payload = build_strategy_account_payload(
        bars=bars,
        orders=orders,
        equity_curve=equity,
        case_id="case_a",
        max_position_symbols=10,
    )

    assert payload["case_id"] == "case_a"
    assert [point["return"] for point in payload["account_curve"]] == [0.0, 0.01, 0.03]
    series = {item["symbol"]: item["points"] for item in payload["position_value_series"]}
    assert [point["market_value"] for point in series["000001.SZ"]] == [1050.0, 1100.0, 720.0]
    assert [point["market_value"] for point in series["600000.SH"]] == [0.0, 1050.0, 1100.0]
    assert payload["summary"]["order_count"] == 3
    assert payload["summary"]["symbol_count"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/charts/test_strategy_account_viewer.py::test_build_strategy_account_payload_reconstructs_position_values -v
```

Expected: fail because `backtest.charts.strategy_account_viewer` does not exist.

- [ ] **Step 3: Implement the minimal payload builder**

Add:

```python
def build_strategy_account_payload(...):
    ...
```

The function must filter by `case_id`, normalize symbols, compute account returns, reconstruct positions, and build `position_value_series`.

- [ ] **Step 4: Run payload test**

Run:

```bash
uv run pytest tests/charts/test_strategy_account_viewer.py::test_build_strategy_account_payload_reconstructs_position_values -v
```

Expected: pass.

## Task 2: Render Static HTML

**Files:**
- Modify: `tests/charts/test_strategy_account_viewer.py`
- Modify: `backtest/charts/strategy_account_viewer.py`

- [ ] **Step 1: Write failing HTML test**

Test that `write_strategy_account_viewer()` embeds the payload and includes:

```text
Holdings Value
Equity/Cash
Return
Order List
Plotly.newPlot
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/charts/test_strategy_account_viewer.py::test_write_strategy_account_viewer_embeds_account_sections -v
```

Expected: fail because HTML rendering is not implemented.

- [ ] **Step 3: Implement HTML rendering**

Add:

```python
def render_strategy_account_viewer_html(payload: dict[str, Any]) -> str:
    ...

def write_strategy_account_viewer(payload: dict[str, Any], output_path: Path) -> None:
    ...
```

The HTML should have three independent Plotly charts:

- Each chart should have a panel-level title header, matching the `Order List` section title style. Plotly annotation titles inside the plotting area should not be rendered.
- `Holdings Value` lines. Zero-value segments should remain visible as flat zero lines so entries and exits are visually continuous.
- `Holdings Value` should expand all symbols by default, sort legend order by each symbol's peak holding market value, and use a paged custom legend with no more than three rows on one page. The page size should be computed from the available legend width so the pager never clips the last legend column.
- `Holdings Value` custom legend interactions: single click toggles one asset, double click isolates one asset, and double clicking the already isolated asset restores all assets.
- `Equity/Cash` lines shown in a Plotly legend at the top of the `Equity/Cash` chart.
- `Return` line shown in a Plotly legend at the top of the `Return` chart.
- Each chart should draw its own x-axis time tick labels instead of sharing or hiding ticks.
- Each chart should use Plotly `x unified` hover with date as the tooltip title and `legend : value` rows only.
- `Holdings Value` hover should omit series whose market value is zero at the hovered date while still drawing their zero-value line segments, and the hover legend color swatches should remain readable.

If a caller explicitly enables aggregation with `max_position_symbols`, the payload should retain the included symbols in `Other.members`, but the first-page chart should not render a separate `Other includes` text block.

The order list should render below the chart.

- [ ] **Step 4: Run HTML test**

Run:

```bash
uv run pytest tests/charts/test_strategy_account_viewer.py::test_write_strategy_account_viewer_embeds_account_sections -v
```

Expected: pass.

## Task 3: Export Public API

**Files:**
- Modify: `backtest/charts/__init__.py`
- Modify: `tests/charts/test_strategy_account_viewer.py`

- [ ] **Step 1: Add import test**

Add an assertion or import using:

```python
from backtest.charts import build_strategy_account_payload, write_strategy_account_viewer
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/charts/test_strategy_account_viewer.py -v
```

Expected: fail until `backtest/charts/__init__.py` exports the new functions.

- [ ] **Step 3: Update exports**

Modify `backtest/charts/__init__.py` to export the new functions.

- [ ] **Step 4: Run chart tests**

Run:

```bash
uv run pytest tests/charts/test_strategy_account_viewer.py tests/charts/test_order_kline_viewer.py tests/charts/test_kline_viewer.py -v
```

Expected: pass.

## Task 4: Generate Example Artifact

**Files:**
- Generated: `runs/charts/strategy_account_viewer_signal_02_hold_20.html`

- [ ] **Step 1: Load case data**

Use `runs/ten_buy_signals/new_runtime_native_20260510/orders.csv` and `equity_curve.csv` for `case_id="signal_02_hold_20"`.

- [ ] **Step 2: Load bars**

Read all parquet bar files under:

```text
data/bars/frequency=1d/adjust=qfq/symbol=<symbol>/year=*/bars.parquet
```

for symbols appearing in the selected case's filled or adjusted orders.

- [ ] **Step 3: Generate HTML**

Write:

```text
runs/charts/strategy_account_viewer_signal_02_hold_20.html
```

- [ ] **Step 4: Verify generated HTML**

Run:

```bash
node -e '<inline script syntax check>'
```

and render a headless Chrome screenshot:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --headless --disable-gpu --window-size=1440,1200 --screenshot=runs/charts/strategy_account_viewer_signal_02_hold_20.png file:///Users/Tyrone.Shi/code-private/backtest/runs/charts/strategy_account_viewer_signal_02_hold_20.html
```

Expected: screenshot shows the three chart sections and full order list.

## Self-Review

- Spec coverage: the plan covers position market value, account cash/equity, strategy return, full order list, tests, and sample artifact generation.
- Placeholder scan: no `TBD`, `TODO`, or undefined implementation steps remain.
- Type consistency: the function names and payload keys match the design spec.
