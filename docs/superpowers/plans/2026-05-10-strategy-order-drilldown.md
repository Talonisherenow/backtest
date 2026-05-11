# Strategy Order Drilldown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a static, hash-routed strategy order drilldown page and link strategy-level order rows to it.

**Architecture:** Reuse the single-symbol order K-line viewer template as the rendering base, extend it to support multi-symbol payloads and `symbol/order_id` hash routing, and add a small strategy-level payload builder. The account viewer emits links to the drilldown artifact instead of owning K-line behavior.

**Tech Stack:** Python, pandas, static HTML, Plotly, pytest.

---

### Task 1: Stable Order IDs

**Files:**
- Modify: `backtest/charts/order_kline_viewer.py`
- Modify: `backtest/charts/strategy_account_viewer.py`
- Test: `tests/charts/test_order_kline_viewer.py`
- Test: `tests/charts/test_strategy_account_viewer.py`

- [x] **Step 1: Write failing tests**

Assert both order payloads expose deterministic IDs such as `order-000000`.

- [x] **Step 2: Implement order IDs**

Derive `order_id` from the original order row index before filtering output columns.

- [x] **Step 3: Verify**

Run:

```bash
uv run pytest tests/charts/test_order_kline_viewer.py tests/charts/test_strategy_account_viewer.py -v
```

### Task 2: Account Viewer Drilldown Links

**Files:**
- Modify: `backtest/charts/strategy_account_viewer.py`
- Test: `tests/charts/test_strategy_account_viewer.py`

- [x] **Step 1: Write failing test**

Assert the account payload contains `links.order_drilldown`, and rendered order rows expose `data-order-id`, `data-symbol`, and drilldown link-building JavaScript.

- [x] **Step 2: Implement link generation**

Add `buildOrderDrilldownHref(order)` in the account viewer template. It writes:

```text
<drilldown file>#symbol=<symbol>&order_id=<order_id>
```

- [x] **Step 3: Verify**

Run the strategy account viewer tests.

### Task 3: Drilldown Payload And Viewer

**Files:**
- Create: `backtest/charts/strategy_order_drilldown_viewer.py`
- Modify: `backtest/charts/__init__.py`
- Test: `tests/charts/test_strategy_order_drilldown_viewer.py`

- [x] **Step 1: Write failing tests**

Assert `build_strategy_order_drilldown_payload()` groups data by symbol and preserves stable order IDs.

- [x] **Step 2: Implement builder**

Build one symbol item per ordered strategy symbol by reusing `build_order_kline_payload()`.

- [x] **Step 3: Implement writer**

Render with the enhanced order K-line template and swap the payload script ID to `strategy-order-drilldown-payload`.

- [x] **Step 4: Verify**

Run the drilldown tests.

### Task 4: Hash-Routed Order Navigation

**Files:**
- Modify: `backtest/charts/order_kline_viewer.py`
- Test: `tests/charts/test_order_kline_viewer.py`
- Test: `tests/charts/test_strategy_order_drilldown_viewer.py`

- [x] **Step 1: Write failing tests**

Assert the HTML contains `readRoute`, `writeRoute`, `applyRoute`, `focusOrder`, `activeOrderId`, `symbolSelect`, and row click handling.

- [x] **Step 2: Implement routing**

Parse `#symbol=...&order_id=...`, switch active symbol data, center the window around the selected order date, and render active marker/row styling.

- [x] **Step 3: Verify**

Run:

```bash
uv run pytest tests/charts/test_order_kline_viewer.py tests/charts/test_strategy_order_drilldown_viewer.py -v
```

### Task 5: Example Artifact

**Files:**
- Generate: `runs/charts/strategy_account_viewer_signal_02_hold_20.html`
- Generate: `runs/charts/strategy_order_drilldown_signal_02_hold_20.html`

- [x] **Step 1: Generate both files**

Use `runs/ten_buy_signals/new_runtime_native_20260510/orders.csv`, `equity_curve.csv`, and cached daily bars for symbols in `case_id="signal_02_hold_20"`.

- [x] **Step 2: Browser verify**

Open the account viewer, click an order, confirm the drilldown page opens with the correct symbol and active order. Then click a different order in the drilldown Order List and confirm the page updates in place.

### Task 6: Keep Rejected Orders Out Of K-line Markers

**Files:**
- Modify: `backtest/charts/order_kline_viewer.py`
- Test: `tests/charts/test_order_kline_viewer.py`

- [x] **Step 1: Write failing test**

Assert the template contains a dedicated `chartOrders()` filter and uses it for buy/sell traces and order annotations.

- [x] **Step 2: Implement chart-only order filtering**

Keep `windowOrders` as the Order List source, but use `chartOrders(windowOrders)` for drawable markers and annotations. `chartOrders()` accepts only `filled` or `adjusted` orders with `filled_shares > 0` and `price > 0`.

- [x] **Step 3: Preserve rejected orders in the list**

Add `Status` and `Reason` columns to the drilldown Order List so rejected orders remain inspectable without being drawn on the K-line.

### Task 7: Add Strategy Result Return Link

**Files:**
- Modify: `backtest/charts/strategy_order_drilldown_viewer.py`
- Modify: `backtest/charts/order_kline_viewer.py`
- Test: `tests/charts/test_strategy_order_drilldown_viewer.py`

- [x] **Step 1: Write failing test**

Assert the drilldown payload contains `links.strategy_account`, and the rendered HTML contains `strategyResultLink` with `Back to Account Viewer`.

- [x] **Step 2: Implement payload link**

Derive the account viewer artifact as `strategy_account_viewer_<case_id>.html` when a case id is available.

- [x] **Step 3: Render header link**

Show the link in the drilldown header when `payload.links.strategy_account` or `metadata.strategy_account_href` is present.
