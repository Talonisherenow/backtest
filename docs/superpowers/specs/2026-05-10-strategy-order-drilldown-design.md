# Strategy Order Drilldown Design

## Goal

`Strategy Account Viewer` is the strategy-level overview. It should let the user click any order and open a symbol-level drilldown page that shows the selected symbol's K-line, all buy/sell markers for that strategy run, and the symbol-specific order list.

The drilldown page should also support clicking its own order list rows. Every order click uses the same navigation semantics: select the order's symbol, move the visible K-line window around that order date, highlight the order marker, and highlight the order row.

## Scope

- Add stable `order_id` values to order payloads.
- Add an account-viewer link from each strategy order row to the drilldown page.
- Add a `Strategy Order Drilldown` payload and static HTML writer.
- Keep the existing single-symbol order K-line viewer usable; enhance its template so it can also consume a multi-symbol drilldown payload.
- Use local `file://` artifacts and hash routing. No server is required.

## Data Contract

`Strategy Account Viewer` order rows include:

```json
{
  "order_id": "order-000123",
  "date": "2025-08-28",
  "symbol": "920855.BJ",
  "side": "buy",
  "filled_shares": 100,
  "price": 12.34
}
```

The account payload includes:

```json
{
  "links": {
    "order_drilldown": "strategy_order_drilldown_signal_02_hold_20.html"
  }
}
```

The drilldown payload includes:

```json
{
  "title": "Strategy Order Drilldown",
  "case_id": "signal_02_hold_20",
  "default_symbol": "002858.SZ",
  "symbols": [
    {
      "symbol": "002858.SZ",
      "bars": [],
      "orders": [],
      "summary": {}
    }
  ]
}
```

## Routing

The drilldown URL uses hash parameters:

```text
strategy_order_drilldown_signal_02_hold_20.html#symbol=002858.SZ&order_id=order-000123
```

Route rules:

- `symbol` selects the active symbol.
- `order_id` selects the active order.
- Changing the symbol updates the chart, metrics, and order list.
- Changing the active order centers the current window around that order date and highlights the row and marker.
- Clicking a row inside the drilldown page writes the same route format, so the page can navigate within itself.

## UI

- The account viewer keeps its current layout. Order rows become clickable.
- The drilldown page keeps the existing K-line window controls: window size, overlap, older/newer/latest, jump-to-time, and slider.
- The drilldown page adds a symbol selector.
- The drilldown page header includes a `Back to Account Viewer` link that returns to the corresponding `Strategy Account Viewer` artifact.
- Buy/sell markers remain visible on the chart; the active order marker gets a stronger outline.
- The active order row uses a subtle highlighted background and left accent.
- The Order List keeps every order in the visible time window, including rejected or otherwise problematic orders, and shows status/reason for inspection.
- The K-line chart only draws executable order markers and annotations: `filled` or `adjusted` orders with `filled_shares > 0` and `price > 0`. Rejected orders stay in the list but do not appear as buy/sell markers on the chart.

## Verification

- Unit tests cover stable `order_id` generation.
- Unit tests cover account viewer drilldown link generation.
- Unit tests cover multi-symbol drilldown payload generation.
- HTML tests cover hash routing functions, symbol selector, order-row click handling, active-order state, and Plotly rendering.
