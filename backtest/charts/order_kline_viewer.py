from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.core.symbols import normalize_symbol

BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]
ORDER_COLUMNS = [
    "date",
    "symbol",
    "side",
    "requested_shares",
    "filled_shares",
    "price",
    "commission",
    "tax",
    "transfer_fee",
    "slippage_cost",
    "status",
    "reason",
]
EQUITY_COLUMNS = ["date", "equity", "cash"]


def build_order_kline_payload(
    *,
    bars: pd.DataFrame,
    orders: pd.DataFrame,
    equity_curve: pd.DataFrame,
    symbol: str,
    case_id: str | None = None,
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_symbol = normalize_symbol(symbol)
    symbol_bars = _filter_bars(bars, normalized_symbol)
    if symbol_bars.empty:
        raise ValueError(f"No bars found for symbol: {normalized_symbol}")

    symbol_orders = _filter_orders(orders, normalized_symbol, case_id)
    selected_equity = _filter_equity(equity_curve, case_id)
    equity_points = _equity_to_json(selected_equity)

    return {
        "title": title or f"{normalized_symbol} Order K-line Viewer",
        "symbol": normalized_symbol,
        "case_id": case_id or "",
        "bars": [_bar_to_json(row) for _, row in symbol_bars[BAR_COLUMNS].iterrows()],
        "orders": [_order_to_json(row) for _, row in symbol_orders.iterrows()],
        "equity_curve": equity_points,
        "summary": _summary(symbol_orders, equity_points),
        "metadata": dict(metadata or {}),
    }


def write_order_kline_viewer(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_order_kline_viewer_html(payload), encoding="utf-8")


def render_order_kline_viewer_html(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    safe_payload = payload_json.replace("</", "<\\/")
    return HTML_TEMPLATE.replace("__ORDER_KLINE_PAYLOAD__", safe_payload)


def _filter_bars(bars: pd.DataFrame, symbol: str) -> pd.DataFrame:
    frame = bars.copy()
    _require_columns(frame, ["date", "symbol", *BAR_COLUMNS[1:]], "bars")
    frame["date"] = pd.to_datetime(frame["date"])
    frame["symbol"] = frame["symbol"].map(lambda value: normalize_symbol(str(value)))
    for column in BAR_COLUMNS[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame[frame["symbol"] == symbol].dropna(subset=BAR_COLUMNS)
    return frame.sort_values("date").drop_duplicates(["date", "symbol"], keep="last").reset_index(drop=True)


def _filter_orders(orders: pd.DataFrame, symbol: str, case_id: str | None) -> pd.DataFrame:
    if orders.empty:
        return pd.DataFrame(columns=[*ORDER_COLUMNS, "order_id"])

    frame = orders.copy()
    _require_columns(frame, ["date", "symbol", "side", "price"], "orders")
    frame["_source_order"] = range(len(frame))
    frame["date"] = pd.to_datetime(frame["date"])
    frame["symbol"] = frame["symbol"].map(lambda value: normalize_symbol(str(value)))
    if case_id and "case_id" in frame.columns:
        frame = frame[frame["case_id"] == case_id]
    frame = frame[frame["symbol"] == symbol].copy()
    for column in ORDER_COLUMNS:
        if column not in frame.columns:
            frame[column] = ""
    for column in [
        "requested_shares",
        "filled_shares",
        "price",
        "commission",
        "tax",
        "transfer_fee",
        "slippage_cost",
    ]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    frame = frame.sort_values(["date", "_source_order"]).reset_index(drop=True)
    frame["order_id"] = frame["_source_order"].map(lambda value: f"order-{int(value):06d}")
    return _attach_order_metrics(frame)[
        [
            "order_id",
            *ORDER_COLUMNS,
            "notional",
            "fee_total",
            "cash_flow",
            "position_after",
            "realized_pnl",
            "realized_return",
        ]
    ]


def _filter_equity(equity_curve: pd.DataFrame, case_id: str | None) -> pd.DataFrame:
    if equity_curve.empty:
        return pd.DataFrame(columns=EQUITY_COLUMNS)

    frame = equity_curve.copy()
    _require_columns(frame, EQUITY_COLUMNS, "equity_curve")
    if case_id and "case_id" in frame.columns:
        frame = frame[frame["case_id"] == case_id]
    frame["date"] = pd.to_datetime(frame["date"])
    frame["equity"] = pd.to_numeric(frame["equity"], errors="coerce")
    frame["cash"] = pd.to_numeric(frame["cash"], errors="coerce")
    return frame.dropna(subset=EQUITY_COLUMNS).sort_values("date").reset_index(drop=True)[EQUITY_COLUMNS]


def _equity_to_json(equity_curve: pd.DataFrame) -> list[dict[str, Any]]:
    if equity_curve.empty:
        return []

    initial_equity = float(equity_curve.iloc[0]["equity"])
    points = []
    for _, row in equity_curve.iterrows():
        equity = float(row["equity"])
        cash = float(row["cash"])
        points.append(
            {
                "date": _date_to_json(row["date"]),
                "equity": equity,
                "cash": cash,
                "return": 0.0 if initial_equity == 0.0 else _round_float(equity / initial_equity - 1.0),
            }
        )
    return points


def _summary(orders: pd.DataFrame, equity_points: list[dict[str, Any]]) -> dict[str, Any]:
    filled = orders[orders["status"].astype(str).isin(["filled", "adjusted"])] if not orders.empty else orders
    buy_count = int((filled["side"].astype(str) == "buy").sum()) if not filled.empty else 0
    sell_count = int((filled["side"].astype(str) == "sell").sum()) if not filled.empty else 0
    realized_pnl = float(filled["realized_pnl"].sum()) if "realized_pnl" in filled else 0.0
    latest = equity_points[-1] if equity_points else {}
    return {
        "order_count": int(len(orders)),
        "filled_order_count": int(len(filled)),
        "buy_order_count": buy_count,
        "sell_order_count": sell_count,
        "realized_pnl": _round_float(realized_pnl),
        "latest_equity": latest.get("equity", 0.0),
        "latest_cash": latest.get("cash", 0.0),
        "total_return": latest.get("return", 0.0),
    }


def _attach_order_metrics(orders: pd.DataFrame) -> pd.DataFrame:
    result = orders.copy()
    result["notional"] = result["filled_shares"] * result["price"]
    result["fee_total"] = (
        result["commission"] + result["tax"] + result["transfer_fee"] + result["slippage_cost"]
    )
    result["cash_flow"] = 0.0
    result["position_after"] = 0.0
    result["realized_pnl"] = 0.0
    result["realized_return"] = 0.0

    lots: list[dict[str, float]] = []
    position = 0.0
    filled_statuses = {"filled", "adjusted"}
    for index, row in result.iterrows():
        side = str(row["side"])
        status = str(row["status"])
        shares = float(row["filled_shares"])
        price = float(row["price"])
        fees = float(row["fee_total"])
        notional = float(row["notional"])

        if status not in filled_statuses or shares <= 0:
            result.at[index, "position_after"] = position
            continue

        if side == "buy":
            cash_flow = -(notional + fees)
            lots.append({"shares": shares, "cost": notional + fees})
            position += shares
        elif side == "sell":
            sell_proceeds = notional - fees
            cost_basis = _consume_lots(lots, shares)
            cash_flow = sell_proceeds
            position = max(position - shares, 0.0)
            realized_pnl = sell_proceeds - cost_basis
            result.at[index, "realized_pnl"] = _round_float(realized_pnl)
            result.at[index, "realized_return"] = _round_float(
                0.0 if cost_basis == 0.0 else realized_pnl / cost_basis
            )
        else:
            cash_flow = 0.0

        result.at[index, "cash_flow"] = _round_float(cash_flow)
        result.at[index, "position_after"] = _round_float(position)

    return result


def _consume_lots(lots: list[dict[str, float]], shares: float) -> float:
    remaining = shares
    consumed_cost = 0.0
    while remaining > 0 and lots:
        lot = lots[0]
        lot_shares = float(lot["shares"])
        take = min(remaining, lot_shares)
        cost_per_share = 0.0 if lot_shares == 0.0 else float(lot["cost"]) / lot_shares
        consumed_cost += take * cost_per_share
        lot["shares"] = lot_shares - take
        lot["cost"] = cost_per_share * lot["shares"]
        remaining -= take
        if lot["shares"] <= 1e-9:
            lots.pop(0)
    return consumed_cost


def _bar_to_json(row: pd.Series) -> dict[str, Any]:
    return {
        "date": _date_to_json(row["date"]),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]),
        "amount": float(row["amount"]),
    }


def _order_to_json(row: pd.Series) -> dict[str, Any]:
    side = str(row["side"])
    price = float(row["price"])
    return {
        "date": _date_to_json(row["date"]),
        "order_id": str(row["order_id"]),
        "symbol": str(row["symbol"]),
        "side": side,
        "requested_shares": float(row["requested_shares"]),
        "filled_shares": float(row["filled_shares"]),
        "price": price,
        "commission": float(row["commission"]),
        "tax": float(row["tax"]),
        "transfer_fee": float(row["transfer_fee"]),
        "slippage_cost": float(row["slippage_cost"]),
        "status": str(row["status"]),
        "reason": "" if pd.isna(row["reason"]) else str(row["reason"]),
        "notional": float(row["notional"]),
        "fee_total": float(row["fee_total"]),
        "cash_flow": float(row["cash_flow"]),
        "position_after": float(row["position_after"]),
        "realized_pnl": float(row["realized_pnl"]),
        "realized_return": float(row["realized_return"]),
        "label": f"{side[:1].upper()} {price:.3f}",
    }


def _date_to_json(value: object) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.time().isoformat() == "00:00:00":
        return timestamp.date().isoformat()
    return timestamp.isoformat()


def _round_float(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return round(float(value), 12)


def _require_columns(frame: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{name} missing columns: {missing}")


_STATIC_ORDER_KLINE_VIEWER_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Order K-line Viewer</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7fb;
      --surface: #ffffff;
      --line: #d8e0e8;
      --text: #1d2733;
      --muted: #667789;
      --buy: #168a5a;
      --sell: #c2412d;
      --blue: #1d5fd1;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    }
    header {
      display: grid;
      grid-template-columns: 1.2fr 2fr;
      gap: 16px;
      padding: 16px 20px 12px;
      background: var(--surface);
      border-bottom: 1px solid var(--line);
    }
    h1 {
      margin: 0;
      font-size: 20px;
      line-height: 1.2;
      letter-spacing: 0;
    }
    .subtitle {
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(7, minmax(94px, 1fr));
      gap: 1px;
      background: var(--line);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    .metric {
      min-width: 0;
      background: var(--surface);
      padding: 9px 11px;
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }
    .metric strong {
      display: block;
      margin-top: 4px;
      font-size: 15px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    main {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 360px;
      gap: 14px;
      padding: 14px 20px 20px;
    }
    #chart {
      width: 100%;
      min-height: 760px;
      height: calc(100vh - 126px);
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    aside {
      min-width: 0;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    aside h2 {
      margin: 0;
      padding: 12px 14px;
      font-size: 15px;
      border-bottom: 1px solid var(--line);
    }
    .table-wrap {
      max-height: calc(100vh - 188px);
      overflow: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    th, td {
      padding: 7px 9px;
      border-bottom: 1px solid #edf1f5;
      text-align: right;
      white-space: nowrap;
    }
    th:first-child, td:first-child { text-align: left; }
    th {
      position: sticky;
      top: 0;
      background: #f8fafc;
      color: var(--muted);
      z-index: 1;
    }
    .buy { color: var(--buy); font-weight: 700; }
    .sell { color: var(--sell); font-weight: 700; }
    @media (max-width: 1040px) {
      header { grid-template-columns: 1fr; }
      main { grid-template-columns: 1fr; }
      #chart { height: 760px; }
      .metrics { grid-template-columns: repeat(3, minmax(94px, 1fr)); }
    }
    @media (max-width: 620px) {
      header, main { padding: 12px; }
      .metrics { grid-template-columns: repeat(2, minmax(94px, 1fr)); }
      #chart { min-height: 640px; }
    }
  </style>
</head>
<body>
  <script id="order-kline-payload" type="application/json">__ORDER_KLINE_PAYLOAD__</script>
  <header>
    <div>
      <h1 id="title">Order K-line Viewer</h1>
      <div class="subtitle" id="subtitle"></div>
    </div>
    <section class="metrics" id="metrics"></section>
  </header>
  <main>
    <section id="chart"></section>
    <aside>
      <h2>Order List</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Side</th>
              <th>Shares</th>
              <th>Price</th>
              <th>Net PnL</th>
              <th>PnL %</th>
              <th>Status</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody id="orderRows"></tbody>
        </table>
      </div>
    </aside>
  </main>
  <script>
    const payload = JSON.parse(document.getElementById("order-kline-payload").textContent);

    const fmtNumber = (value, digits = 2) => Number(value || 0).toLocaleString(undefined, {
      maximumFractionDigits: digits,
      minimumFractionDigits: digits
    });
    const fmtPercent = (value) => `${(Number(value || 0) * 100).toFixed(2)}%`;
    const fmtSigned = (value, digits = 2) => {
      const numeric = Number(value || 0);
      const sign = numeric > 0 ? "+" : "";
      return `${sign}${fmtNumber(numeric, digits)}`;
    };

    document.getElementById("title").textContent = payload.title || "Order K-line Viewer";
    document.getElementById("subtitle").textContent = `${payload.symbol} · ${payload.case_id || "case"} · ${payload.bars.length} bars · ${payload.orders.length} orders`;

    const metricItems = [
      ["Orders", payload.summary.order_count],
      ["Filled", payload.summary.filled_order_count],
      ["Buy/Sell", `${payload.summary.buy_order_count}/${payload.summary.sell_order_count}`],
      ["Realized PnL", fmtSigned(payload.summary.realized_pnl || 0)],
      ["Equity", fmtNumber(payload.summary.latest_equity)],
      ["Cash", fmtNumber(payload.summary.latest_cash)],
      ["Return", fmtPercent(payload.summary.total_return)]
    ];
    document.getElementById("metrics").innerHTML = metricItems.map(([label, value]) => (
      `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`
    )).join("");

    const bars = payload.bars;
    const orders = payload.orders;
    const equity = payload.equity_curve;
    const dates = bars.map((bar) => bar.date);
    const buyOrders = orders.filter((order) => order.side === "buy");
    const sellOrders = orders.filter((order) => order.side === "sell");
    const orderLabel = (prefix, order) => order.label || `${prefix} ${fmtNumber(order.price, 3)}`;
    const orderHover = (order) => [
      `${order.side.toUpperCase()} ${order.symbol || payload.symbol}`,
      `date: ${order.date}`,
      `shares: ${fmtNumber(order.filled_shares, 0)}`,
      `price: ${fmtNumber(order.price, 3)}`,
      `fee: ${fmtNumber(order.fee_total, 2)}`,
      order.realized_pnl ? `net PnL: ${fmtSigned(order.realized_pnl)}` : "",
      order.realized_return ? `PnL %: ${fmtPercent(order.realized_return)}` : "",
      `position after: ${fmtNumber(order.position_after, 0)}`,
      `status: ${order.status}`,
      order.reason ? `reason: ${order.reason}` : ""
    ].filter(Boolean).join("<br>");
    const orderAnnotations = orders.map((order) => {
      const isBuy = order.side === "buy";
      const color = isBuy ? "#168a5a" : "#c2412d";
      return {
        x: order.date,
        y: order.price,
        xref: "x",
        yref: "y",
        text: orderLabel(isBuy ? "B" : "S", order),
        showarrow: true,
        arrowhead: 2,
        arrowsize: 1,
        arrowwidth: 1.5,
        arrowcolor: color,
        ax: 0,
        ay: isBuy ? 38 : -38,
        bgcolor: "rgba(255,255,255,0.96)",
        bordercolor: color,
        borderwidth: 1,
        borderpad: 3,
        font: { color, size: 12, family: "Arial, sans-serif" }
      };
    });

    const traces = [
      {
        type: "candlestick",
        name: "K-line",
        x: dates,
        open: bars.map((bar) => bar.open),
        high: bars.map((bar) => bar.high),
        low: bars.map((bar) => bar.low),
        close: bars.map((bar) => bar.close),
        increasing: { line: { color: "#c2412d" }, fillcolor: "rgba(194,65,45,0.18)" },
        decreasing: { line: { color: "#168a5a" }, fillcolor: "rgba(22,138,90,0.18)" },
        xaxis: "x",
        yaxis: "y"
      },
      {
        type: "scatter",
        mode: "markers",
        name: "Buy Orders",
        x: buyOrders.map((order) => order.date),
        y: buyOrders.map((order) => order.price),
        customdata: buyOrders.map(orderHover),
        hovertemplate: "%{customdata}<extra></extra>",
        marker: { symbol: "circle", size: 9, color: "#168a5a", line: { color: "#ffffff", width: 2 } },
        xaxis: "x",
        yaxis: "y"
      },
      {
        type: "scatter",
        mode: "markers",
        name: "Sell Orders",
        x: sellOrders.map((order) => order.date),
        y: sellOrders.map((order) => order.price),
        customdata: sellOrders.map(orderHover),
        hovertemplate: "%{customdata}<extra></extra>",
        marker: { symbol: "circle", size: 9, color: "#c2412d", line: { color: "#ffffff", width: 2 } },
        xaxis: "x",
        yaxis: "y"
      },
      {
        type: "bar",
        name: "Volume",
        x: dates,
        y: bars.map((bar) => bar.volume),
        marker: { color: bars.map((bar) => bar.close >= bar.open ? "rgba(194,65,45,0.45)" : "rgba(22,138,90,0.45)") },
        xaxis: "x2",
        yaxis: "y2"
      },
      {
        type: "scatter",
        mode: "lines",
        name: "Equity",
        x: equity.map((point) => point.date),
        y: equity.map((point) => point.equity),
        line: { color: "#1d5fd1", width: 2 },
        xaxis: "x3",
        yaxis: "y3"
      },
      {
        type: "scatter",
        mode: "lines",
        name: "Cash",
        x: equity.map((point) => point.date),
        y: equity.map((point) => point.cash),
        line: { color: "#667789", width: 1.6 },
        xaxis: "x3",
        yaxis: "y3"
      },
      {
        type: "scatter",
        mode: "lines",
        name: "Return",
        x: equity.map((point) => point.date),
        y: equity.map((point) => point.return),
        line: { color: "#7c3aed", width: 2 },
        hovertemplate: "%{x}<br>Return: %{y:.2%}<extra></extra>",
        xaxis: "x4",
        yaxis: "y4"
      }
    ];

    const layout = {
      margin: { l: 56, r: 30, t: 36, b: 40 },
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#ffffff",
      hovermode: "x unified",
      showlegend: true,
      legend: { orientation: "h", x: 0, y: 1.04, xanchor: "left", yanchor: "bottom" },
      xaxis: { type: "category", rangeslider: { visible: false }, domain: [0, 1], anchor: "y", showticklabels: false },
      yaxis: { title: { text: "Price" }, domain: [0.53, 1], fixedrange: false, tickformat: ".2f" },
      xaxis2: { type: "category", matches: "x", anchor: "y2", showticklabels: false },
      yaxis2: { title: { text: "Volume" }, domain: [0.39, 0.49], fixedrange: false },
      xaxis3: { type: "category", matches: "x", anchor: "y3", showticklabels: false },
      yaxis3: { title: { text: "Equity / Cash" }, domain: [0.19, 0.35], fixedrange: false, tickformat: ".0f" },
      xaxis4: { type: "category", matches: "x", anchor: "y4" },
      yaxis4: { title: { text: "Return" }, domain: [0, 0.15], fixedrange: false, tickformat: ".1%" },
      bargap: 0.15,
      annotations: [
        { text: "Price + Orders", xref: "paper", yref: "paper", x: 0, y: 1.02, showarrow: false, font: { size: 12, color: "#667789" } },
        { text: "Volume", xref: "paper", yref: "paper", x: 0, y: 0.49, showarrow: false, font: { size: 12, color: "#667789" } },
        { text: "Account Equity / Cash", xref: "paper", yref: "paper", x: 0, y: 0.35, showarrow: false, font: { size: 12, color: "#667789" } },
        { text: "Return", xref: "paper", yref: "paper", x: 0, y: 0.15, showarrow: false, font: { size: 12, color: "#667789" } }
      ].concat(orderAnnotations)
    };

    Plotly.newPlot("chart", traces, layout, { responsive: true, displaylogo: false });

    document.getElementById("orderRows").innerHTML = orders.map((order) => (
      `<tr>
        <td>${order.date}</td>
        <td class="${order.side === "buy" ? "buy" : "sell"}">${order.side}</td>
        <td>${fmtNumber(order.filled_shares, 0)}</td>
        <td>${fmtNumber(order.price, 3)}</td>
        <td>${fmtNumber(order.fee_total, 2)}</td>
        <td class="${order.realized_pnl > 0 ? "buy" : order.realized_pnl < 0 ? "sell" : ""}">${order.realized_pnl ? fmtSigned(order.realized_pnl) : ""}</td>
        <td class="${order.realized_return > 0 ? "buy" : order.realized_return < 0 ? "sell" : ""}">${order.realized_return ? fmtPercent(order.realized_return) : ""}</td>
        <td>${order.status}</td>
      </tr>`
    )).join("");
  </script>
</body>
</html>
"""


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Order K-line Viewer</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f7fb;
      --surface: #ffffff;
      --line: #d8e0e8;
      --line-soft: #edf1f5;
      --text: #1d2733;
      --muted: #667789;
      --buy: #168a5a;
      --sell: #c2412d;
      --blue: #1d5fd1;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 20;
      background: var(--surface);
      border-bottom: 1px solid var(--line);
      padding: 14px 20px 12px;
    }
    .topline {
      display: grid;
      grid-template-columns: minmax(240px, 1fr) auto;
      gap: 16px;
      align-items: start;
    }
    h1 {
      margin: 0;
      font-size: 20px;
      line-height: 1.2;
      letter-spacing: 0;
    }
    .subtitle, .dataset-meta, .position-meta span {
      color: var(--muted);
      font-size: 12px;
    }
    .subtitle { margin-top: 6px; }
    .dataset-meta { text-align: right; }
    .header-actions {
      display: grid;
      gap: 6px;
      justify-items: end;
    }
    .back-link {
      display: inline-flex;
      align-items: center;
      height: 30px;
      padding: 0 11px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #ffffff;
      color: var(--text);
      font-size: 12px;
      font-weight: 700;
      text-decoration: none;
      white-space: nowrap;
    }
    .back-link:hover {
      border-color: #b8c4d1;
      background: #f8fafc;
    }
    .back-link[hidden] { display: none; }
    .time-window {
      display: grid;
      grid-template-columns: minmax(160px, 210px) repeat(2, minmax(120px, 150px)) auto minmax(170px, 210px) auto minmax(240px, 1fr);
      gap: 10px;
      align-items: end;
      margin-top: 12px;
    }
    label {
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }
    select, input, button {
      height: 32px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #ffffff;
      color: var(--text);
      font: inherit;
      letter-spacing: 0;
    }
    select, input { padding: 0 9px; }
    button {
      padding: 0 12px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 700;
    }
    button:disabled, input:disabled, select:disabled {
      cursor: default;
      opacity: 0.5;
    }
    .window-actions {
      display: flex;
      gap: 6px;
    }
    .window-position {
      display: grid;
      grid-template-columns: minmax(140px, 1fr) 170px;
      gap: 10px;
      align-items: center;
      height: 32px;
    }
    #windowSlider { width: 100%; padding: 0; }
    .position-meta {
      min-width: 0;
      display: grid;
      gap: 2px;
    }
    .position-meta strong {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 12px;
      line-height: 1.1;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(5, minmax(110px, 1fr));
      gap: 1px;
      margin: 12px 20px 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: var(--line);
    }
    .metric {
      min-width: 0;
      background: var(--surface);
      padding: 9px 11px;
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }
    .metric strong {
      display: block;
      margin-top: 4px;
      font-size: 15px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    main {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 380px;
      gap: 14px;
      padding: 14px 20px 20px;
    }
    #chart {
      width: 100%;
      min-height: 620px;
      height: calc(100vh - 210px);
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    #chart.empty {
      display: grid;
      place-items: center;
      color: var(--muted);
      font-weight: 700;
    }
    aside {
      min-width: 0;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    aside h2 {
      margin: 0;
      padding: 12px 14px 4px;
      font-size: 15px;
    }
    .order-meta {
      padding: 0 14px 10px;
      color: var(--muted);
      font-size: 12px;
      border-bottom: 1px solid var(--line);
    }
    .table-wrap {
      max-height: calc(100vh - 280px);
      overflow: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    th, td {
      padding: 7px 9px;
      border-bottom: 1px solid var(--line-soft);
      text-align: right;
      white-space: nowrap;
    }
    th:first-child, td:first-child { text-align: left; }
    th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: #f8fafc;
      color: var(--muted);
    }
    .buy { color: var(--buy); font-weight: 700; }
    .sell { color: var(--sell); font-weight: 700; }
    tr[data-order-id] { cursor: pointer; }
    tr[data-order-id]:hover td { background: #f8fafc; }
    .order-row-active td {
      background: #fff8df;
      box-shadow: inset 3px 0 0 #f59e0b;
    }
    .empty-cell {
      color: var(--muted);
      text-align: center;
      padding: 20px 10px;
    }
    @media (max-width: 1160px) {
      .topline { grid-template-columns: 1fr; }
      .dataset-meta { text-align: left; }
      .header-actions { justify-items: start; }
      .time-window { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .position-control { grid-column: 1 / -1; }
      main { grid-template-columns: 1fr; }
      #chart { height: 680px; }
      .summary { grid-template-columns: repeat(3, minmax(110px, 1fr)); }
    }
    @media (max-width: 680px) {
      header { padding: 12px; }
      .summary, main { margin-left: 12px; margin-right: 12px; padding-left: 0; padding-right: 0; }
      main { display: block; }
      aside { margin-top: 12px; }
      .time-window { grid-template-columns: 1fr; }
      .window-actions { display: grid; grid-template-columns: repeat(3, 1fr); }
      .window-position { grid-template-columns: 1fr; height: auto; }
      .summary { grid-template-columns: repeat(2, minmax(110px, 1fr)); }
      #chart { min-height: 560px; }
    }
  </style>
</head>
<body>
  <script id="order-kline-payload" type="application/json">__ORDER_KLINE_PAYLOAD__</script>
  <header>
    <div class="topline">
      <div>
        <h1 id="title">Order K-line Viewer</h1>
        <div class="subtitle" id="subtitle"></div>
      </div>
      <div class="header-actions">
        <a class="back-link" id="strategyResultLink" href="#" hidden>Back to Account Viewer</a>
        <div class="dataset-meta" id="datasetMeta"></div>
      </div>
    </div>
    <div class="time-window" id="timeWindowBar">
      <label class="symbol-control">Symbol
        <select id="symbolSelect"></select>
      </label>
      <label>Window
        <select id="windowSizeSelect">
          <option value="100">100 bars</option>
          <option value="300">300 bars</option>
          <option value="1000">1000 bars</option>
          <option value="5000">5000 bars</option>
          <option value="all">All available</option>
        </select>
      </label>
      <label class="overlap-control">Overlap
        <select id="windowOverlapSelect">
          <option value="0">0%</option>
          <option value="0.1">10%</option>
          <option value="0.2">20%</option>
          <option value="0.5">50%</option>
          <option value="0.8" selected>80%</option>
        </select>
      </label>
      <div class="window-actions" aria-label="Window navigation">
        <button type="button" id="olderPageButton">Older</button>
        <button type="button" id="newerPageButton">Newer</button>
        <button type="button" id="latestPageButton">Latest</button>
      </div>
      <label class="jump-control">Jump to
        <input id="jumpTimeInput" type="datetime-local" autocomplete="off">
      </label>
      <button type="button" id="jumpTimeButton">Go</button>
      <label class="position-control">Position
        <div class="window-position">
          <input id="windowSlider" type="range" min="0" max="0" value="0">
          <div class="position-meta" id="windowMeta">
            <strong id="windowRowsMeta">Rows</strong>
            <span id="windowTimeMeta">Latest window</span>
          </div>
        </div>
      </label>
    </div>
  </header>
  <section class="summary" id="metrics"></section>
  <main>
    <section id="chart"></section>
    <aside>
      <h2>Order List</h2>
      <div class="order-meta" id="orderListMeta"></div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Side</th>
              <th>Shares</th>
              <th>Price</th>
              <th>Net PnL</th>
              <th>PnL %</th>
              <th>Status</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody id="orderRows"></tbody>
        </table>
      </div>
    </aside>
  </main>
  <script>
    const payload = JSON.parse(document.getElementById("order-kline-payload").textContent);
    const symbolItems = Array.isArray(payload.symbols) && payload.symbols.length
      ? payload.symbols
      : [{
        symbol: payload.symbol || "",
        bars: Array.isArray(payload.bars) ? payload.bars : [],
        orders: Array.isArray(payload.orders) ? payload.orders : [],
        summary: payload.summary || {},
      }];
    const bySymbol = new Map(symbolItems.map((item) => [item.symbol, item]));
    const strategyResultHref = payload.links?.strategy_account || payload.metadata?.strategy_account_href || "";
    const state = {
      symbol: payload.default_symbol || payload.symbol || symbolItems[0]?.symbol || "",
      activeOrderId: "",
      windowSize: String(payload.default_window_size || payload.metadata?.default_window_size || 100),
      windowOverlap: String(payload.default_window_overlap ?? payload.metadata?.default_window_overlap ?? 0.8),
      windowStart: 0,
    };
    let activeItem = bySymbol.get(state.symbol) || symbolItems[0] || { symbol: "", bars: [], orders: [], summary: {} };
    let bars = Array.isArray(activeItem.bars) ? activeItem.bars : [];
    let orders = Array.isArray(activeItem.orders) ? activeItem.orders : [];

    const chart = document.getElementById("chart");
    const metrics = document.getElementById("metrics");
    const datasetMeta = document.getElementById("datasetMeta");
    const strategyResultLink = document.getElementById("strategyResultLink");
    const orderRows = document.getElementById("orderRows");
    const orderListMeta = document.getElementById("orderListMeta");
    const symbolSelect = document.getElementById("symbolSelect");
    const windowSizeSelect = document.getElementById("windowSizeSelect");
    const windowOverlapSelect = document.getElementById("windowOverlapSelect");
    const windowSlider = document.getElementById("windowSlider");
    const windowRowsMeta = document.getElementById("windowRowsMeta");
    const windowTimeMeta = document.getElementById("windowTimeMeta");
    const olderPageButton = document.getElementById("olderPageButton");
    const newerPageButton = document.getElementById("newerPageButton");
    const latestPageButton = document.getElementById("latestPageButton");
    const jumpTimeInput = document.getElementById("jumpTimeInput");
    const jumpTimeButton = document.getElementById("jumpTimeButton");

    const fmtNumber = (value, digits = 2) => Number(value || 0).toLocaleString(undefined, {
      maximumFractionDigits: digits,
      minimumFractionDigits: digits
    });
    const fmtPercent = (value) => `${(Number(value || 0) * 100).toFixed(2)}%`;
    const fmtSigned = (value, digits = 2) => {
      const numeric = Number(value || 0);
      const sign = numeric > 0 ? "+" : "";
      return `${sign}${fmtNumber(numeric, digits)}`;
    };
    const fixed = (value, digits = 2) => Number(value || 0).toFixed(digits);
    const compact = (value) => {
      const number = Number(value);
      if (!Number.isFinite(number)) {
        return "0";
      }
      if (Math.abs(number) >= 100000000) {
        return `${fixed(number / 100000000)}B`;
      }
      if (Math.abs(number) >= 10000) {
        return `${fixed(number / 10000)}W`;
      }
      return `${Math.round(number)}`;
    };
    const escapeHtml = (value) => String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");

    if (strategyResultHref) {
      strategyResultLink.href = strategyResultHref;
      strategyResultLink.hidden = false;
    }

    function readRoute() {
      const params = new URLSearchParams(String(window.location.hash || "").replace(/^#/, ""));
      return {
        symbol: params.get("symbol") || "",
        orderId: params.get("order_id") || params.get("orderId") || "",
      };
    }

    function writeRoute(symbol, orderId = "") {
      const params = new URLSearchParams();
      if (symbol) {
        params.set("symbol", symbol);
      }
      if (orderId) {
        params.set("order_id", orderId);
      }
      window.location.hash = params.toString();
    }

    function updateActiveSymbolData() {
      activeItem = bySymbol.get(state.symbol) || symbolItems[0] || { symbol: "", bars: [], orders: [], summary: {} };
      state.symbol = activeItem.symbol || state.symbol;
      bars = Array.isArray(activeItem.bars) ? activeItem.bars : [];
      orders = Array.isArray(activeItem.orders) ? activeItem.orders : [];
    }

    function renderSymbolOptions() {
      symbolSelect.innerHTML = symbolItems.map((item) => {
        const selected = item.symbol === state.symbol ? " selected" : "";
        return `<option value="${escapeHtml(item.symbol)}"${selected}>${escapeHtml(item.symbol)}</option>`;
      }).join("");
      symbolSelect.disabled = symbolItems.length <= 1;
    }

    function renderHeader() {
      document.getElementById("title").textContent = payload.title || "Order K-line Viewer";
      document.getElementById("subtitle").textContent = [
        state.symbol,
        payload.case_id || "case",
        `${compact(bars.length)} bars`,
        `${compact(orders.length)} orders`,
      ].filter(Boolean).join(" | ");
      datasetMeta.textContent = [
        `Symbol: ${state.symbol || ""}`,
        payload.case_id ? `Case: ${payload.case_id}` : "",
        state.activeOrderId ? `Active order: ${state.activeOrderId}` : "orders as enrichment",
      ].filter(Boolean).join(" | ");
      symbolSelect.value = state.symbol;
    }

    function toTime(value) {
      const raw = String(value || "");
      if (!raw) {
        return NaN;
      }
      const parsed = new Date(raw.includes("T") ? raw : raw.replace(" ", "T"));
      return parsed.getTime();
    }

    function isDailySeries() {
      return bars.every((bar) => !String(bar.date || "").includes("T") && !String(bar.date || "").includes(" "));
    }

    function windowSizeValue() {
      if (state.windowSize === "all") {
        return bars.length;
      }
      return Math.min(Math.max(1, Number(state.windowSize) || 100), bars.length);
    }

    function requestedWindowSize() {
      if (state.windowSize === "all") {
        return Math.max(1, bars.length);
      }
      return Math.max(1, Number(state.windowSize) || 100);
    }

    function clamp(value, min, max) {
      return Math.min(Math.max(value, min), max);
    }

    function windowOverlapRatio() {
      const value = Number(state.windowOverlap);
      return Number.isFinite(value) ? clamp(value, 0, 0.9) : 0.8;
    }

    function pageStepSize() {
      const size = requestedWindowSize();
      if (state.windowSize === "all") {
        return size;
      }
      return Math.max(1, Math.round(size * (1 - windowOverlapRatio())));
    }

    function maxWindowStart() {
      return Math.max(0, bars.length - windowSizeValue());
    }

    function setWindowToLatest() {
      state.windowStart = maxWindowStart();
    }

    function visibleBars() {
      const size = windowSizeValue();
      const maxStart = maxWindowStart();
      state.windowStart = clamp(state.windowStart, 0, maxStart);
      if (size >= bars.length) {
        return bars;
      }
      return bars.slice(state.windowStart, state.windowStart + size);
    }

    function inWindow(point, windowBars) {
      if (!windowBars.length) {
        return false;
      }
      const start = toTime(windowBars[0].date);
      const end = toTime(windowBars[windowBars.length - 1].date);
      const value = toTime(point.date);
      if (!Number.isFinite(start) || !Number.isFinite(end) || !Number.isFinite(value)) {
        return String(point.date) >= String(windowBars[0].date) && String(point.date) <= String(windowBars[windowBars.length - 1].date);
      }
      return value >= start && value <= end;
    }

    function visibleOrders(windowBars) {
      return orders.filter((order) => inWindow(order, windowBars));
    }

    function chartOrders(windowOrders) {
      return windowOrders.filter((order) => (
        ["filled", "adjusted"].includes(String(order.status || "").toLowerCase())
        && Number(order.filled_shares || 0) > 0
        && Number(order.price || 0) > 0
      ));
    }

    function configureJumpControl() {
      const daily = isDailySeries();
      jumpTimeInput.type = daily ? "date" : "datetime-local";
      jumpTimeInput.step = daily ? "86400" : "60";
      jumpTimeInput.min = bars[0]?.date ? String(bars[0].date).slice(0, daily ? 10 : 16) : "";
      jumpTimeInput.max = bars[bars.length - 1]?.date ? String(bars[bars.length - 1].date).slice(0, daily ? 10 : 16) : "";
      jumpTimeInput.title = [bars[0]?.date, bars[bars.length - 1]?.date].filter(Boolean).join(" to ");
    }

    function updateWindowControls(windowBars) {
      const size = windowSizeValue();
      const maxStart = maxWindowStart();
      windowSizeSelect.value = state.windowSize;
      windowOverlapSelect.value = state.windowOverlap;
      windowOverlapSelect.disabled = maxStart === 0;
      windowSlider.max = String(maxStart);
      windowSlider.value = String(state.windowStart);
      windowSlider.disabled = maxStart === 0;
      const startRow = windowBars.length ? state.windowStart + 1 : 0;
      const endRow = windowBars.length ? Math.min(bars.length, state.windowStart + windowBars.length) : 0;
      windowRowsMeta.textContent = windowBars.length
        ? `Rows ${startRow}-${endRow} / ${compact(bars.length)}`
        : "No bars";
      windowTimeMeta.textContent = windowBars.length
        ? `${windowBars[0].date} to ${windowBars[windowBars.length - 1].date}`
        : "No window selected";
      olderPageButton.disabled = !windowBars.length || state.windowStart <= 0;
      newerPageButton.disabled = !windowBars.length || state.windowStart >= maxStart;
      latestPageButton.disabled = !windowBars.length || state.windowStart >= maxStart;
      jumpTimeButton.disabled = !bars.length;
      configureJumpControl();
    }

    function movingAverage(sourceBars, days) {
      return sourceBars.map((_, index) => {
        if (index + 1 < days) {
          return null;
        }
        const window = sourceBars.slice(index + 1 - days, index + 1);
        return window.reduce((sum, bar) => sum + Number(bar.close), 0) / days;
      });
    }

    function metric(label, value) {
      return `<div class="metric"><span>${escapeHtml(label)}</span><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`;
    }

    function renderMetrics(windowBars, windowOrders) {
      if (!windowBars.length) {
        metrics.innerHTML = metric("Status", "No data");
        return;
      }
      const first = windowBars[0];
      const last = windowBars[windowBars.length - 1];
      const change = Number(last.close || 0) - Number(first.close || 0);
      const changePct = first.close ? change / Number(first.close) : 0;
      const windowPnl = windowOrders.reduce((total, order) => total + Number(order.realized_pnl || 0), 0);
      metrics.innerHTML = [
        metric("Window", `${first.date} to ${last.date}`),
        metric("Close", fixed(last.close)),
        metric("Change", `${fmtSigned(change)} (${fmtPercent(changePct)})`),
        metric("Orders", `${windowOrders.length} / ${orders.length}`),
        metric("Window PnL", fmtSigned(windowPnl)),
      ].join("");
    }

    const orderLabel = (prefix, order) => order.label || `${prefix} ${fmtNumber(order.price, 3)}`;
    const orderHover = (order) => [
      `${String(order.side || "").toUpperCase()} ${order.symbol || state.symbol || ""}`,
      `date: ${order.date}`,
      `shares: ${fmtNumber(order.filled_shares, 0)}`,
      `price: ${fmtNumber(order.price, 3)}`,
      `fee: ${fmtNumber(order.fee_total, 2)}`,
      order.realized_pnl ? `net PnL: ${fmtSigned(order.realized_pnl)}` : "",
      order.realized_return ? `PnL %: ${fmtPercent(order.realized_return)}` : "",
      `position after: ${fmtNumber(order.position_after, 0)}`,
      `status: ${order.status || ""}`,
      order.reason ? `reason: ${order.reason}` : ""
    ].filter(Boolean).join("<br>");

    function orderAnnotations(windowOrders) {
      return windowOrders.map((order) => {
        const isBuy = order.side === "buy";
        const color = isBuy ? "#168a5a" : "#c2412d";
        const active = order.order_id && order.order_id === state.activeOrderId;
        return {
          x: order.date,
          y: order.price,
          xref: "x",
          yref: "y",
          text: orderLabel(isBuy ? "B" : "S", order),
          showarrow: true,
          arrowhead: 2,
          arrowsize: 1,
          arrowwidth: 1.5,
          arrowcolor: color,
          ax: 0,
          ay: isBuy ? 36 : -36,
          bgcolor: active ? "#fff8df" : "rgba(255,255,255,0.96)",
          bordercolor: color,
          borderwidth: active ? 2 : 1,
          borderpad: 3,
          font: { color, size: active ? 13 : 12, family: "Arial, sans-serif" }
        };
      });
    }

    function orderMarker(windowOrders, color) {
      return {
        symbol: "circle",
        size: windowOrders.map((order) => order.order_id === state.activeOrderId ? 14 : 9),
        color,
        line: {
          color: windowOrders.map((order) => order.order_id === state.activeOrderId ? "#f59e0b" : "#ffffff"),
          width: windowOrders.map((order) => order.order_id === state.activeOrderId ? 3 : 2),
        },
      };
    }

    function renderOrderRows(windowOrders, windowBars) {
      orderListMeta.textContent = windowBars.length
        ? `${windowOrders.length} orders in ${windowBars[0].date} to ${windowBars[windowBars.length - 1].date}`
        : "No visible window";
      if (!windowOrders.length) {
        orderRows.innerHTML = `<tr><td class="empty-cell" colspan="8">No orders in current window</td></tr>`;
        return;
      }
      orderRows.innerHTML = windowOrders.map((order) => (
        `<tr data-order-id="${escapeHtml(order.order_id || "")}" data-symbol="${escapeHtml(order.symbol || state.symbol || "")}" class="${order.order_id === state.activeOrderId ? "order-row-active" : ""}">
          <td>${escapeHtml(order.date)}</td>
          <td class="${order.side === "buy" ? "buy" : "sell"}">${escapeHtml(order.side)}</td>
          <td>${fmtNumber(order.filled_shares, 0)}</td>
          <td>${fmtNumber(order.price, 3)}</td>
          <td class="${order.realized_pnl > 0 ? "buy" : order.realized_pnl < 0 ? "sell" : ""}">${order.realized_pnl ? fmtSigned(order.realized_pnl) : ""}</td>
          <td class="${order.realized_return > 0 ? "buy" : order.realized_return < 0 ? "sell" : ""}">${order.realized_return ? fmtPercent(order.realized_return) : ""}</td>
          <td>${escapeHtml(order.status || "")}</td>
          <td>${escapeHtml(order.reason || "")}</td>
        </tr>`
      )).join("");
    }

    function render() {
      renderHeader();
      const windowBars = visibleBars();
      updateWindowControls(windowBars);
      const windowOrders = visibleOrders(windowBars);
      renderMetrics(windowBars, windowOrders);
      renderOrderRows(windowOrders, windowBars);

      if (!windowBars.length) {
        chart.className = "empty";
        chart.textContent = "No bars";
        return;
      }
      chart.className = "";
      chart.textContent = "";
      if (!window.Plotly) {
        chart.className = "empty";
        chart.textContent = "Chart library failed to load";
        return;
      }

      const x = windowBars.map((bar) => bar.date);
      const drawableOrders = chartOrders(windowOrders);
      const buyOrders = drawableOrders.filter((order) => order.side === "buy");
      const sellOrders = drawableOrders.filter((order) => order.side === "sell");
      const upColor = "#c2412d";
      const downColor = "#168a5a";
      const volumeColors = windowBars.map((bar) => Number(bar.close) >= Number(bar.open) ? "rgba(194,65,45,0.48)" : "rgba(22,138,90,0.48)");
      const traces = [
        {
          type: "candlestick",
          name: "K-line",
          x,
          open: windowBars.map((bar) => bar.open),
          high: windowBars.map((bar) => bar.high),
          low: windowBars.map((bar) => bar.low),
          close: windowBars.map((bar) => bar.close),
          increasing: { line: { color: upColor }, fillcolor: "rgba(194,65,45,0.18)" },
          decreasing: { line: { color: downColor }, fillcolor: "rgba(22,138,90,0.18)" },
          xaxis: "x",
          yaxis: "y"
        },
        {
          type: "scatter",
          mode: "lines",
          name: "MA5",
          x,
          y: movingAverage(windowBars, 5),
          line: { color: "#f9a825", width: 1.4 },
          xaxis: "x",
          yaxis: "y"
        },
        {
          type: "scatter",
          mode: "lines",
          name: "MA20",
          x,
          y: movingAverage(windowBars, 20),
          line: { color: "#1565c0", width: 1.4 },
          xaxis: "x",
          yaxis: "y"
        },
        {
          type: "scatter",
          mode: "markers",
          name: "Buy Orders",
          x: buyOrders.map((order) => order.date),
          y: buyOrders.map((order) => order.price),
          customdata: buyOrders.map(orderHover),
          hovertemplate: "%{customdata}<extra></extra>",
          marker: orderMarker(buyOrders, "#168a5a"),
          xaxis: "x",
          yaxis: "y"
        },
        {
          type: "scatter",
          mode: "markers",
          name: "Sell Orders",
          x: sellOrders.map((order) => order.date),
          y: sellOrders.map((order) => order.price),
          customdata: sellOrders.map(orderHover),
          hovertemplate: "%{customdata}<extra></extra>",
          marker: orderMarker(sellOrders, "#c2412d"),
          xaxis: "x",
          yaxis: "y"
        },
        {
          type: "bar",
          name: "Volume",
          x,
          y: windowBars.map((bar) => bar.volume),
          marker: { color: volumeColors },
          xaxis: "x2",
          yaxis: "y2"
        }
      ];

      const layout = {
        margin: { l: 60, r: 28, t: 38, b: 42 },
        paper_bgcolor: "#ffffff",
        plot_bgcolor: "#ffffff",
        hovermode: "x unified",
        showlegend: true,
        legend: { orientation: "h", x: 0, y: 1.05, xanchor: "left", yanchor: "bottom" },
        xaxis: { type: "category", rangeslider: { visible: false }, domain: [0, 1], anchor: "y", showticklabels: false, showgrid: true, gridcolor: "#edf1f5", nticks: 9 },
        yaxis: { title: { text: "Price" }, domain: [0.27, 1], fixedrange: false, tickformat: ".2f", showgrid: true, gridcolor: "#edf1f5" },
        xaxis2: { type: "category", matches: "x", anchor: "y2", nticks: 9 },
        yaxis2: { title: { text: "Volume" }, domain: [0, 0.18], fixedrange: false, showgrid: true, gridcolor: "#edf1f5" },
        bargap: 0.12,
        annotations: [
          { text: "Price + Orders", xref: "paper", yref: "paper", x: 0, y: 1.02, showarrow: false, font: { size: 12, color: "#667789" } },
          { text: "Volume", xref: "paper", yref: "paper", x: 0, y: 0.18, showarrow: false, font: { size: 12, color: "#667789" } }
        ].concat(orderAnnotations(drawableOrders))
      };
      Plotly.newPlot(chart, traces, layout, { responsive: true, displaylogo: false });
    }

    function ensureWindowOption() {
      if (!Array.from(windowSizeSelect.options).some((option) => option.value === state.windowSize)) {
        windowSizeSelect.insertAdjacentHTML(
          "beforeend",
          `<option value="${escapeHtml(state.windowSize)}">${escapeHtml(state.windowSize)} bars</option>`
        );
      }
      windowSizeSelect.value = state.windowSize;
    }

    function ensureWindowOverlapOption() {
      state.windowOverlap = String(windowOverlapRatio());
      if (!Array.from(windowOverlapSelect.options).some((option) => option.value === state.windowOverlap)) {
        windowOverlapSelect.insertAdjacentHTML(
          "beforeend",
          `<option value="${escapeHtml(state.windowOverlap)}">${Math.round(windowOverlapRatio() * 100)}%</option>`
        );
      }
      windowOverlapSelect.value = state.windowOverlap;
    }

    function setWindowAroundDate(raw, centered = false) {
      if (!raw || !bars.length) {
        return;
      }
      const index = bars.findIndex((bar) => String(bar.date) >= raw);
      const targetIndex = index < 0 ? bars.length - 1 : index;
      const offset = centered ? Math.floor(windowSizeValue() / 2) : 0;
      state.windowStart = clamp(targetIndex - offset, 0, maxWindowStart());
    }

    function focusOrder(orderId) {
      const order = orders.find((item) => item.order_id === orderId);
      if (!order) {
        return;
      }
      state.activeOrderId = order.order_id;
      setWindowAroundDate(order.date, true);
    }

    function jumpToTime() {
      const raw = jumpTimeInput.value.trim();
      if (!raw) {
        return;
      }
      setWindowAroundDate(raw);
      state.activeOrderId = "";
      render();
    }

    function applyRoute() {
      const route = readRoute();
      const nextSymbol = bySymbol.has(route.symbol) ? route.symbol : state.symbol;
      const symbolChanged = nextSymbol !== state.symbol;
      state.symbol = nextSymbol;
      state.activeOrderId = route.orderId || "";
      updateActiveSymbolData();
      if (symbolChanged) {
        setWindowToLatest();
      }
      if (state.activeOrderId) {
        focusOrder(state.activeOrderId);
      }
      render();
    }

    symbolSelect.addEventListener("change", () => {
      writeRoute(symbolSelect.value, "");
    });
    windowSizeSelect.addEventListener("change", () => {
      state.windowSize = windowSizeSelect.value;
      if (state.activeOrderId) {
        focusOrder(state.activeOrderId);
      } else {
        setWindowToLatest();
      }
      render();
    });
    windowOverlapSelect.addEventListener("change", () => {
      state.windowOverlap = windowOverlapSelect.value;
      render();
    });
    olderPageButton.addEventListener("click", () => {
      state.windowStart = clamp(state.windowStart - pageStepSize(), 0, maxWindowStart());
      render();
    });
    newerPageButton.addEventListener("click", () => {
      state.windowStart = clamp(state.windowStart + pageStepSize(), 0, maxWindowStart());
      render();
    });
    latestPageButton.addEventListener("click", () => {
      setWindowToLatest();
      render();
    });
    windowSlider.addEventListener("input", () => {
      state.windowStart = clamp(Number(windowSlider.value), 0, maxWindowStart());
      render();
    });
    jumpTimeButton.addEventListener("click", jumpToTime);
    jumpTimeInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        jumpToTime();
      }
    });
    orderRows.addEventListener("click", (event) => {
      const row = event.target.closest("tr[data-order-id]");
      if (!row) {
        return;
      }
      writeRoute(row.dataset.symbol || state.symbol, row.dataset.orderId || "");
    });
    window.addEventListener("hashchange", applyRoute);
    window.addEventListener("resize", () => {
      if (chart.data) {
        Plotly.Plots.resize(chart);
      }
    });

    const initialRoute = readRoute();
    if (initialRoute.symbol && bySymbol.has(initialRoute.symbol)) {
      state.symbol = initialRoute.symbol;
    }
    state.activeOrderId = initialRoute.orderId;
    updateActiveSymbolData();
    renderSymbolOptions();
    ensureWindowOption();
    ensureWindowOverlapOption();
    if (state.activeOrderId) {
      focusOrder(state.activeOrderId);
    } else {
      setWindowToLatest();
    }
    render();
  </script>
</body>
</html>
"""
