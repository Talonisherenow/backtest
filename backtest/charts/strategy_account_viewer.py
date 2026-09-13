from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.core.symbols import normalize_symbol

FILLED_STATUSES = {"filled", "adjusted"}
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


def build_strategy_account_payload(
    *,
    bars: pd.DataFrame,
    orders: pd.DataFrame,
    equity_curve: pd.DataFrame,
    case_id: str | None = None,
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
    max_position_symbols: int | None = None,
) -> dict[str, Any]:
    selected_orders = _filter_orders(orders, case_id)
    selected_equity = _filter_equity(equity_curve, case_id)
    account_curve = _account_curve_to_json(selected_equity)
    position_value_series = _position_value_series(
        bars=bars,
        orders=selected_orders,
        account_curve=selected_equity,
        max_position_symbols=max_position_symbols,
    )

    return {
        "title": title or _default_title(case_id),
        "case_id": case_id or "",
        "account_curve": account_curve,
        "position_value_series": position_value_series,
        "orders": [_order_to_json(row) for _, row in selected_orders.iterrows()],
        "links": {"order_drilldown": _default_order_drilldown_href(case_id)},
        "summary": _summary(
            orders=selected_orders,
            account_curve=account_curve,
        ),
        "metadata": dict(metadata or {}),
    }


def write_strategy_account_viewer(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_strategy_account_viewer_html(payload), encoding="utf-8")


def render_strategy_account_viewer_html(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    safe_payload = payload_json.replace("</", "<\\/")
    return HTML_TEMPLATE.replace("__STRATEGY_ACCOUNT_PAYLOAD__", safe_payload)


def _default_title(case_id: str | None) -> str:
    return f"{case_id} Strategy Account Viewer" if case_id else "Strategy Account Viewer"


def _default_order_drilldown_href(case_id: str | None) -> str:
    return f"strategy_order_drilldown_{case_id}.html" if case_id else "strategy_order_drilldown.html"


def _filter_orders(orders: pd.DataFrame, case_id: str | None) -> pd.DataFrame:
    if orders.empty:
        return pd.DataFrame(columns=["order_id", *ORDER_COLUMNS, "notional", "fee_total"])

    frame = orders.copy()
    _require_columns(frame, ["date", "symbol", "side", "price"], "orders")
    frame["_source_order"] = range(len(frame))
    frame["date"] = pd.to_datetime(frame["date"])
    frame["symbol"] = frame["symbol"].map(lambda value: normalize_symbol(str(value)))
    if case_id and "case_id" in frame.columns:
        frame = frame[frame["case_id"] == case_id].copy()

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
    frame["status"] = frame["status"].astype(str)
    frame["side"] = frame["side"].astype(str)
    frame["notional"] = frame["filled_shares"] * frame["price"]
    frame["fee_total"] = frame["commission"] + frame["tax"] + frame["transfer_fee"] + frame["slippage_cost"]
    frame["order_id"] = frame["_source_order"].map(lambda value: f"order-{int(value):06d}")
    output_columns = ["order_id", *ORDER_COLUMNS, "notional", "fee_total"]
    for optional_column in ("signal_id", "signal_label", "signal_date"):
        if optional_column in frame.columns:
            output_columns.append(optional_column)
    return (
        frame.sort_values(["date", "_source_order"], kind="mergesort")
        .reset_index(drop=True)[output_columns]
    )


def _filter_equity(equity_curve: pd.DataFrame, case_id: str | None) -> pd.DataFrame:
    if equity_curve.empty:
        return pd.DataFrame(columns=EQUITY_COLUMNS)

    frame = equity_curve.copy()
    _require_columns(frame, EQUITY_COLUMNS, "equity_curve")
    if case_id and "case_id" in frame.columns:
        frame = frame[frame["case_id"] == case_id].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["equity"] = pd.to_numeric(frame["equity"], errors="coerce")
    frame["cash"] = pd.to_numeric(frame["cash"], errors="coerce")
    return frame.dropna(subset=EQUITY_COLUMNS).sort_values("date").reset_index(drop=True)[EQUITY_COLUMNS]


def _clean_bars(bars: pd.DataFrame, symbols: set[str]) -> pd.DataFrame:
    if bars.empty:
        return pd.DataFrame(columns=["date", "symbol", "close"])

    frame = bars.copy()
    _require_columns(frame, ["date", "symbol", "close"], "bars")
    frame["date"] = pd.to_datetime(frame["date"])
    frame["symbol"] = frame["symbol"].map(lambda value: normalize_symbol(str(value)))
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    if symbols:
        frame = frame[frame["symbol"].isin(symbols)]
    return (
        frame.dropna(subset=["date", "symbol", "close"])
        .sort_values(["date", "symbol"], kind="mergesort")
        .drop_duplicates(["date", "symbol"], keep="last")
        .reset_index(drop=True)[["date", "symbol", "close"]]
    )


def _account_curve_to_json(equity_curve: pd.DataFrame) -> list[dict[str, Any]]:
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
                "equity": _round_float(equity),
                "cash": _round_float(cash),
                "return": 0.0 if initial_equity == 0.0 else _round_float(equity / initial_equity - 1.0),
            }
        )
    return points


def _position_value_series(
    *,
    bars: pd.DataFrame,
    orders: pd.DataFrame,
    account_curve: pd.DataFrame,
    max_position_symbols: int | None,
) -> list[dict[str, Any]]:
    filled_orders = _filled_orders(orders)
    symbols = set(filled_orders["symbol"].astype(str)) if not filled_orders.empty else set()
    clean_bars = _clean_bars(bars, symbols)
    timeline = _timeline(account_curve, filled_orders, clean_bars)
    if not timeline or not symbols:
        return []

    orders_by_date = {
        date: group.sort_index()
        for date, group in filled_orders.groupby("date", sort=False)
    }
    bars_by_date = {
        date: group
        for date, group in clean_bars.groupby("date", sort=False)
    }
    positions: defaultdict[str, float] = defaultdict(float)
    last_close: dict[str, float] = {}
    points_by_symbol: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in sorted(symbols)}

    for trade_date in timeline:
        day_bars = bars_by_date.get(trade_date)
        if day_bars is not None:
            for _, row in day_bars.iterrows():
                last_close[str(row["symbol"])] = float(row["close"])

        day_orders = orders_by_date.get(trade_date)
        if day_orders is not None:
            for _, order in day_orders.iterrows():
                symbol = str(order["symbol"])
                shares = float(order["filled_shares"])
                side = str(order["side"])
                if float(order["price"]) > 0 and symbol not in last_close:
                    last_close[symbol] = float(order["price"])
                if side == "buy":
                    positions[symbol] += shares
                elif side == "sell":
                    positions[symbol] = max(0.0, positions[symbol] - shares)

        for symbol in sorted(symbols):
            shares = _round_float(positions[symbol])
            price = last_close.get(symbol, 0.0)
            points_by_symbol[symbol].append(
                {
                    "date": _date_to_json(trade_date),
                    "shares": shares,
                    "market_value": _round_float(shares * price),
                }
            )

    return _limit_position_series(points_by_symbol, max_position_symbols)


def _filled_orders(orders: pd.DataFrame) -> pd.DataFrame:
    if orders.empty:
        return orders.copy()
    return orders[
        orders["status"].astype(str).isin(FILLED_STATUSES)
        & (orders["filled_shares"].astype(float) > 0.0)
    ].copy()


def _timeline(account_curve: pd.DataFrame, orders: pd.DataFrame, bars: pd.DataFrame) -> list[pd.Timestamp]:
    if not account_curve.empty:
        return list(account_curve["date"].drop_duplicates().sort_values())
    dates = []
    if not orders.empty:
        dates.extend(orders["date"].drop_duplicates().tolist())
    if not bars.empty:
        dates.extend(bars["date"].drop_duplicates().tolist())
    return sorted(pd.Timestamp(value) for value in set(dates))


def _limit_position_series(
    points_by_symbol: dict[str, list[dict[str, Any]]],
    max_position_symbols: int | None,
) -> list[dict[str, Any]]:
    ranked = sorted(
        points_by_symbol.items(),
        key=lambda item: max((float(point["market_value"]) for point in item[1]), default=0.0),
        reverse=True,
    )
    if max_position_symbols is None:
        return [{"symbol": symbol, "points": points} for symbol, points in ranked]

    limit = max(1, int(max_position_symbols))
    kept = ranked[:limit]
    remaining = ranked[limit:]
    result = [{"symbol": symbol, "points": points} for symbol, points in kept]
    if remaining:
        dates = [point["date"] for point in kept[0][1]] if kept else [point["date"] for point in remaining[0][1]]
        members = [symbol for symbol, _ in remaining]
        other_points = []
        for index, date in enumerate(dates):
            other_points.append(
                {
                    "date": date,
                    "shares": 0.0,
                    "market_value": _round_float(
                        sum(float(points[index]["market_value"]) for _, points in remaining)
                    ),
                }
            )
        result.append({"symbol": "Other", "members": members, "points": other_points})
    return result


def _order_to_json(row: pd.Series) -> dict[str, Any]:
    signal_id = "" if "signal_id" not in row.index or pd.isna(row["signal_id"]) else str(row["signal_id"])
    signal_label = "" if "signal_label" not in row.index or pd.isna(row["signal_label"]) else str(row["signal_label"])
    signal_date = "" if "signal_date" not in row.index or pd.isna(row["signal_date"]) else str(row["signal_date"])
    return {
        "date": _date_to_json(row["date"]),
        "order_id": str(row["order_id"]),
        "symbol": str(row["symbol"]),
        "side": str(row["side"]),
        "requested_shares": float(row["requested_shares"]),
        "filled_shares": float(row["filled_shares"]),
        "price": float(row["price"]),
        "fee_total": _round_float(float(row["fee_total"])),
        "notional": _round_float(float(row["notional"])),
        "status": str(row["status"]),
        "reason": "" if pd.isna(row["reason"]) else str(row["reason"]),
        "signal_id": signal_id,
        "signal_label": signal_label,
        "signal_date": signal_date,
    }


def _summary(
    *,
    orders: pd.DataFrame,
    account_curve: list[dict[str, Any]],
) -> dict[str, Any]:
    filled = _filled_orders(orders)
    latest = account_curve[-1] if account_curve else {}
    first = account_curve[0] if account_curve else {}
    start_date = first.get("date") or ""
    end_date = latest.get("date") or ""
    symbols = set(filled["symbol"].astype(str)) if not filled.empty else set()
    return {
        "start_date": start_date,
        "end_date": end_date,
        "symbol_count": int(len(symbols)),
        "order_count": int(len(orders)),
        "filled_order_count": int(len(filled)),
        "initial_equity": first.get("equity", 0.0),
        "latest_equity": latest.get("equity", 0.0),
        "latest_cash": latest.get("cash", 0.0),
        "total_return": latest.get("return", 0.0),
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


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Strategy Account Viewer</title>
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
      --purple: #6d42ff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    }
    header {
      padding: 16px 20px 12px;
      background: var(--surface);
      border-bottom: 1px solid var(--line);
    }
    .topline {
      display: grid;
      grid-template-columns: minmax(240px, 1fr) auto;
      gap: 16px;
      align-items: start;
    }
    h1 {
      margin: 0;
      font-size: 21px;
      line-height: 1.2;
      letter-spacing: 0;
    }
    .subtitle, .dataset-meta {
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
    .metrics {
      display: grid;
      grid-template-columns: repeat(7, minmax(110px, 1fr));
      gap: 1px;
      margin-top: 14px;
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
      gap: 14px;
      padding: 14px 20px 20px;
    }
    .chart-panel {
      width: 100%;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    .chart {
      width: 100%;
      background: var(--surface);
    }
    #holdingsChart { height: 430px; }
    #accountChart, #returnChart { height: 270px; }
    .panel-header,
    .orders-header {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
    }
    .panel-header h2,
    .orders h2 {
      margin: 0;
      font-size: 15px;
    }
    .holdings-legend-shell {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto auto;
      gap: 10px;
      align-items: start;
      padding: 12px 88px 0;
    }
    .holdings-legend-title {
      color: var(--muted);
      font-size: 12px;
      line-height: 20px;
      white-space: nowrap;
    }
    .holdings-legend {
      display: grid;
      grid-auto-flow: column;
      grid-template-rows: repeat(3, 20px);
      grid-auto-columns: max-content;
      column-gap: 14px;
      row-gap: 0;
      min-width: 0;
      overflow: hidden;
    }
    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      width: 132px;
      height: 20px;
      padding: 0;
      border: 0;
      background: transparent;
      color: var(--text);
      font: inherit;
      font-size: 12px;
      line-height: 20px;
      cursor: pointer;
    }
    .legend-item[aria-pressed="false"] {
      opacity: 0.36;
    }
    .legend-swatch {
      width: 28px;
      height: 2px;
      flex: 0 0 auto;
    }
    .legend-label {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .legend-page {
      color: var(--muted);
      font-size: 12px;
      line-height: 24px;
      white-space: nowrap;
    }
    .legend-pager {
      display: flex;
      gap: 4px;
    }
    .legend-nav {
      width: 24px;
      height: 24px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--surface);
      color: var(--text);
      cursor: pointer;
      line-height: 20px;
      padding: 0;
    }
    .legend-nav:disabled {
      color: #aab5c1;
      cursor: default;
    }
    .orders {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    .orders-meta {
      color: var(--muted);
      font-size: 12px;
    }
    .table-wrap {
      max-height: 360px;
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
    th:first-child, td:first-child,
    th:nth-child(2), td:nth-child(2) { text-align: left; }
    th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: #f8fafc;
      color: var(--muted);
    }
    .buy { color: var(--buy); font-weight: 700; }
    .sell { color: var(--sell); font-weight: 700; }
    .order-link {
      color: inherit;
      text-decoration: none;
    }
    tr[data-order-id] {
      cursor: pointer;
    }
    tr[data-order-id]:hover td {
      background: #f8fafc;
    }
    @media (max-width: 960px) {
      .topline { grid-template-columns: 1fr; }
      .dataset-meta { text-align: left; }
      .header-actions { justify-items: start; }
      .metrics { grid-template-columns: repeat(3, minmax(110px, 1fr)); }
      #holdingsChart { height: 420px; }
      #accountChart, #returnChart { height: 260px; }
    }
    @media (max-width: 620px) {
      header, main { padding-left: 12px; padding-right: 12px; }
      .metrics { grid-template-columns: repeat(2, minmax(110px, 1fr)); }
      .holdings-legend-shell {
        grid-template-columns: 1fr auto auto;
        padding-left: 16px;
        padding-right: 16px;
      }
      .holdings-legend-title { display: none; }
      #holdingsChart { height: 390px; }
      #accountChart, #returnChart { height: 250px; }
    }
  </style>
</head>
<body>
  <script id="strategy-account-payload" type="application/json">__STRATEGY_ACCOUNT_PAYLOAD__</script>
  <header>
    <div class="topline">
      <div>
        <h1 id="title">Strategy Account Viewer</h1>
        <div class="subtitle" id="subtitle"></div>
      </div>
      <div class="header-actions">
        <a class="back-link" id="strategyResultsLink" href="#" hidden>Back to Results Catalog</a>
        <div class="dataset-meta" id="datasetMeta"></div>
      </div>
    </div>
    <section class="metrics" id="metrics"></section>
  </header>
  <main>
    <section class="chart-panel">
      <div class="panel-header"><h2>Holdings Value</h2></div>
      <div class="holdings-legend-shell">
        <div class="holdings-legend-title">Holdings</div>
        <div class="holdings-legend" id="holdingsLegend"></div>
        <div class="legend-page" id="holdingsLegendPage"></div>
        <div class="legend-pager">
          <button class="legend-nav" id="holdingsLegendPrev" type="button" aria-label="Previous holdings legend page">‹</button>
          <button class="legend-nav" id="holdingsLegendNext" type="button" aria-label="Next holdings legend page">›</button>
        </div>
      </div>
      <section class="chart" id="holdingsChart"></section>
    </section>
    <section class="chart-panel">
      <div class="panel-header"><h2>Equity/Cash</h2></div>
      <section class="chart" id="accountChart"></section>
    </section>
    <section class="chart-panel">
      <div class="panel-header"><h2>Return</h2></div>
      <section class="chart" id="returnChart"></section>
    </section>
    <section class="orders">
      <div class="orders-header">
        <h2>Order List</h2>
        <div class="orders-meta" id="ordersMeta"></div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>Symbol</th>
              <th>Side</th>
              <th>Signal</th>
              <th>Shares</th>
              <th>Price</th>
              <th>Notional</th>
              <th>Fee</th>
              <th>Status</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody id="orderRows"></tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    const payload = JSON.parse(document.getElementById("strategy-account-payload").textContent);
    const accountCurve = Array.isArray(payload.account_curve) ? payload.account_curve : [];
    const positionSeries = Array.isArray(payload.position_value_series) ? payload.position_value_series : [];
    const orders = Array.isArray(payload.orders) ? payload.orders : [];
    const summary = payload.summary || {};
    const orderDrilldownHref = payload.links?.order_drilldown || payload.metadata?.order_drilldown_href || "";
    const strategyResultsHref = payload.links?.result_catalog || payload.metadata?.result_catalog_href || "";
    const strategyResultsLink = document.getElementById("strategyResultsLink");

    const fmtNumber = (value, digits = 2) => Number(value || 0).toLocaleString(undefined, {
      maximumFractionDigits: digits,
      minimumFractionDigits: digits
    });
    const fmtPercent = (value) => `${(Number(value || 0) * 100).toFixed(2)}%`;
    const compact = (value) => {
      const number = Number(value);
      if (!Number.isFinite(number)) return "0";
      if (Math.abs(number) >= 100000000) return `${(number / 100000000).toFixed(2)}B`;
      if (Math.abs(number) >= 10000) return `${(number / 10000).toFixed(2)}W`;
      return `${Math.round(number)}`;
    };
    const escapeHtml = (value) => String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
    const buildOrderDrilldownHref = (order) => {
      if (!orderDrilldownHref || !order?.symbol || !order?.order_id) {
        return "";
      }
      const params = new URLSearchParams();
      params.set("symbol", order.symbol);
      params.set("order_id", order.order_id);
      return `${orderDrilldownHref}#${params.toString()}`;
    };

    document.getElementById("title").textContent = payload.title || "Strategy Account Viewer";
    document.getElementById("subtitle").textContent = [
      payload.case_id || "case",
      `${summary.start_date || ""} to ${summary.end_date || ""}`,
      `${summary.symbol_count || 0} symbols`,
      `${summary.order_count || 0} orders`
    ].filter(Boolean).join(" | ");
    document.getElementById("datasetMeta").textContent = "strategy account view";
    if (strategyResultsHref) {
      strategyResultsLink.href = strategyResultsHref;
      strategyResultsLink.hidden = false;
    }

    function metric(label, value) {
      return `<div class="metric"><span>${escapeHtml(label)}</span><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`;
    }

    document.getElementById("metrics").innerHTML = [
      metric("Period", `${summary.start_date || "-"} to ${summary.end_date || "-"}`),
      metric("Symbols", compact(summary.symbol_count || 0)),
      metric("Orders", `${compact(summary.filled_order_count || 0)} / ${compact(summary.order_count || 0)}`),
      metric("Initial Equity", fmtNumber(summary.initial_equity || 0)),
      metric("Latest Equity", fmtNumber(summary.latest_equity || 0)),
      metric("Latest Cash", fmtNumber(summary.latest_cash || 0)),
      metric("Total Return", fmtPercent(summary.total_return || 0)),
    ].join("");

    const plotlyPalette = [
      "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
      "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"
    ];
    const HOLDINGS_LEGEND_ROWS = 3;
    const HOLDINGS_LEGEND_ITEM_WIDTH = 132;
    const HOLDINGS_LEGEND_COLUMN_GAP = 14;
    let holdingsLegendPage = 0;
    let holdingsLegendClickTimer = null;
    const activePositionSymbols = new Set(positionSeries.map((series) => series.symbol));

    function traceColor(index) {
      return plotlyPalette[index % plotlyPalette.length];
    }

    function positiveMarketValue(value) {
      const numeric = Number(value || 0);
      return numeric > 0 ? numeric : null;
    }

    const positionLineTraces = positionSeries.map((series, index) => ({
      type: "scatter",
      mode: "lines",
      name: series.symbol,
      x: series.points.map((point) => point.date),
      y: series.points.map((point) => point.market_value),
      line: { color: traceColor(index) },
      hoverinfo: "skip",
      showlegend: false,
    }));

    const positionHoverTraces = positionSeries.map((series, index) => ({
      type: "scatter",
      mode: "lines",
      name: series.symbol,
      x: series.points.map((point) => point.date),
      y: series.points.map((point) => positiveMarketValue(point.market_value)),
      line: { color: traceColor(index), width: 2 },
      showlegend: false,
      hovertemplate: `${series.symbol} : %{y:~s}<extra></extra>`,
    }));
    const positionTraces = positionLineTraces.concat(positionHoverTraces);

    function holdingsLegendPageSize() {
      const legend = document.getElementById("holdingsLegend");
      const availableWidth = Math.max(0, legend.clientWidth || 0);
      const columnWidth = HOLDINGS_LEGEND_ITEM_WIDTH + HOLDINGS_LEGEND_COLUMN_GAP;
      const columns = Math.max(1, Math.floor((availableWidth + HOLDINGS_LEGEND_COLUMN_GAP) / columnWidth));
      return HOLDINGS_LEGEND_ROWS * columns;
    }

    function renderHoldingsLegend() {
      const legend = document.getElementById("holdingsLegend");
      const pageLabel = document.getElementById("holdingsLegendPage");
      const previous = document.getElementById("holdingsLegendPrev");
      const next = document.getElementById("holdingsLegendNext");
      const pageSize = holdingsLegendPageSize();
      const pageCount = Math.max(1, Math.ceil(positionSeries.length / pageSize));
      holdingsLegendPage = Math.min(Math.max(holdingsLegendPage, 0), pageCount - 1);
      const start = holdingsLegendPage * pageSize;
      const pageSeries = positionSeries.slice(start, start + pageSize);
      legend.innerHTML = pageSeries.map((series, pageIndex) => {
        const seriesIndex = start + pageIndex;
        const active = activePositionSymbols.has(series.symbol);
        return `<button class="legend-item" type="button" data-index="${seriesIndex}" aria-pressed="${active ? "true" : "false"}" title="${escapeHtml(series.symbol)}">
          <span class="legend-swatch" style="background:${traceColor(seriesIndex)}"></span>
          <span class="legend-label">${escapeHtml(series.symbol)}</span>
        </button>`;
      }).join("");
      pageLabel.textContent = `${holdingsLegendPage + 1} / ${pageCount}`;
      previous.disabled = holdingsLegendPage === 0;
      next.disabled = holdingsLegendPage >= pageCount - 1;
    }

    function setPositionSeriesVisible(index, visible) {
      const symbol = positionSeries[index]?.symbol;
      if (!symbol) {
        return;
      }
      if (visible) {
        activePositionSymbols.add(symbol);
      } else {
        activePositionSymbols.delete(symbol);
      }
      Plotly.restyle("holdingsChart", { visible: visible ? true : false }, [
        index,
        index + positionSeries.length,
      ]);
    }

    function togglePositionSeries(index) {
      const symbol = positionSeries[index]?.symbol;
      if (!symbol) {
        return;
      }
      setPositionSeriesVisible(index, !activePositionSymbols.has(symbol));
      renderHoldingsLegend();
    }

    function showAllPositionSeries() {
      positionSeries.forEach((_series, index) => {
        setPositionSeriesVisible(index, true);
      });
      renderHoldingsLegend();
    }

    function isolatePositionSeries(index) {
      positionSeries.forEach((_series, seriesIndex) => {
        setPositionSeriesVisible(seriesIndex, seriesIndex === index);
      });
      renderHoldingsLegend();
    }

    function holdingsLegendButtonFromEvent(event) {
      return event.target.closest("[data-index]");
    }

    function handleHoldingsLegendClick(event) {
      const button = holdingsLegendButtonFromEvent(event);
      if (!button || event.detail > 1) {
        return;
      }
      if (holdingsLegendClickTimer) {
        window.clearTimeout(holdingsLegendClickTimer);
      }
      const index = Number(button.dataset.index);
      holdingsLegendClickTimer = window.setTimeout(() => {
        togglePositionSeries(index);
        holdingsLegendClickTimer = null;
      }, 220);
    }

    function handleHoldingsLegendDoubleClick(event) {
      const button = holdingsLegendButtonFromEvent(event);
      if (!button) {
        return;
      }
      if (holdingsLegendClickTimer) {
        window.clearTimeout(holdingsLegendClickTimer);
        holdingsLegendClickTimer = null;
      }
      const index = Number(button.dataset.index);
      const symbol = positionSeries[index]?.symbol;
      if (!symbol) {
        return;
      }
      if (activePositionSymbols.size === 1 && activePositionSymbols.has(symbol)) {
        showAllPositionSeries();
      } else {
        isolatePositionSeries(index);
      }
    }

    const accountTraces = [
      {
        type: "scatter",
        mode: "lines",
        name: "Equity",
        x: accountCurve.map((point) => point.date),
        y: accountCurve.map((point) => point.equity),
        line: { color: "#1d5fd1", width: 2.2 },
      },
      {
        type: "scatter",
        mode: "lines",
        name: "Cash",
        x: accountCurve.map((point) => point.date),
        y: accountCurve.map((point) => point.cash),
        line: { color: "#667789", width: 1.8 },
      }
    ];

    const returnTrace = {
      type: "scatter",
      mode: "lines",
      name: "Return",
      x: accountCurve.map((point) => point.date),
      y: accountCurve.map((point) => point.return),
      line: { color: "#6d42ff", width: 2.2 },
      hovertemplate: "Return : %{y:.2%}<extra></extra>",
    };

    function chartLayout(yTitle, yTickFormat, options = {}) {
      return {
        margin: { l: 88, r: 30, t: 42, b: 42 },
        paper_bgcolor: "#ffffff",
        plot_bgcolor: "#ffffff",
        hovermode: "x unified",
        showlegend: options.showlegend ?? true,
        legend: { orientation: "h", x: 0, y: 1.14, xanchor: "left", yanchor: "bottom" },
        xaxis: { type: "category", showgrid: true, gridcolor: "#edf1f5", nticks: 10 },
        yaxis: { title: { text: yTitle }, fixedrange: false, tickformat: yTickFormat, hoverformat: yTickFormat, showgrid: true, gridcolor: "#edf1f5" },
      };
    }

    const chartConfig = { responsive: true, displaylogo: false };
    Plotly.newPlot(
      "holdingsChart",
      positionTraces,
      chartLayout("Holdings Value", "~s", { showlegend: false }),
      chartConfig
    ).then(renderHoldingsLegend);
    Plotly.newPlot("accountChart", accountTraces, chartLayout("Equity/Cash", "~s"), chartConfig);
    Plotly.newPlot("returnChart", [returnTrace], chartLayout("Return", ".1%"), chartConfig);

    document.getElementById("holdingsLegend").addEventListener("click", handleHoldingsLegendClick);
    document.getElementById("holdingsLegend").addEventListener("dblclick", handleHoldingsLegendDoubleClick);
    document.getElementById("holdingsLegendPrev").addEventListener("click", () => {
      holdingsLegendPage -= 1;
      renderHoldingsLegend();
    });
    document.getElementById("holdingsLegendNext").addEventListener("click", () => {
      holdingsLegendPage += 1;
      renderHoldingsLegend();
    });

    document.getElementById("ordersMeta").textContent = `${orders.length} orders`;
    document.getElementById("orderRows").innerHTML = orders.map((order) => {
      const href = buildOrderDrilldownHref(order);
      const dateCell = href
        ? `<a class="order-link" href="${escapeHtml(href)}">${escapeHtml(order.date)}</a>`
        : escapeHtml(order.date);
      return `<tr data-order-id="${escapeHtml(order.order_id || "")}" data-symbol="${escapeHtml(order.symbol || "")}" data-drilldown-href="${escapeHtml(href)}">
        <td>${dateCell}</td>
        <td>${escapeHtml(order.symbol)}</td>
        <td class="${order.side === "buy" ? "buy" : order.side === "sell" ? "sell" : ""}">${escapeHtml(order.side)}</td>
        <td>${escapeHtml(order.signal_label || order.signal_id || "")}</td>
        <td>${fmtNumber(order.filled_shares, 0)}</td>
        <td>${fmtNumber(order.price, 3)}</td>
        <td>${fmtNumber(order.notional, 2)}</td>
        <td>${fmtNumber(order.fee_total, 2)}</td>
        <td>${escapeHtml(order.status)}</td>
        <td>${escapeHtml(order.reason)}</td>
      </tr>`;
    }).join("");
    document.getElementById("orderRows").addEventListener("click", (event) => {
      if (event.target.closest("a")) {
        return;
      }
      const row = event.target.closest("tr[data-drilldown-href]");
      const href = row?.dataset?.drilldownHref;
      if (href) {
        window.location.href = href;
      }
    });

    window.addEventListener("resize", () => {
      renderHoldingsLegend();
      for (const chartId of ["holdingsChart", "accountChart", "returnChart"]) {
        const chart = document.getElementById(chartId);
        if (chart.data) {
          Plotly.Plots.resize(chart);
        }
      }
    });
  </script>
</body>
</html>
"""
