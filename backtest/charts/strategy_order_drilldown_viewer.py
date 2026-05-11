from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from backtest.charts.order_kline_viewer import build_order_kline_payload, render_order_kline_viewer_html
from backtest.core.symbols import normalize_symbol


def build_strategy_order_drilldown_payload(
    *,
    bars: pd.DataFrame,
    orders: pd.DataFrame,
    equity_curve: pd.DataFrame,
    case_id: str | None = None,
    default_symbol: str | None = None,
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    symbols = _ordered_symbols(orders, case_id)
    symbol_payloads = [
        build_order_kline_payload(
            bars=bars,
            orders=orders,
            equity_curve=equity_curve,
            symbol=symbol,
            case_id=case_id,
            title=f"{symbol} Strategy Order Drilldown",
            metadata=metadata,
        )
        for symbol in symbols
        if _has_symbol_bars(bars, symbol)
    ]
    normalized_default = normalize_symbol(default_symbol) if default_symbol else ""
    if normalized_default not in {item["symbol"] for item in symbol_payloads}:
        normalized_default = symbol_payloads[0]["symbol"] if symbol_payloads else ""

    return {
        "title": title or "Strategy Order Drilldown",
        "case_id": case_id or "",
        "default_symbol": normalized_default,
        "symbols": [
            {
                "symbol": item["symbol"],
                "bars": item["bars"],
                "orders": item["orders"],
                "summary": item["summary"],
            }
            for item in symbol_payloads
        ],
        "summary": {
            "symbol_count": len(symbol_payloads),
            "order_count": sum(len(item["orders"]) for item in symbol_payloads),
        },
        "links": {"strategy_account": _default_strategy_account_href(case_id)},
        "metadata": dict(metadata or {}),
    }


def write_strategy_order_drilldown_viewer(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_strategy_order_drilldown_viewer_html(payload), encoding="utf-8")


def render_strategy_order_drilldown_viewer_html(payload: dict[str, Any]) -> str:
    html = render_order_kline_viewer_html(payload)
    return (
        html.replace("<title>Order K-line Viewer</title>", "<title>Strategy Order Drilldown</title>")
        .replace('id="order-kline-payload"', 'id="strategy-order-drilldown-payload"')
        .replace(
            'getElementById("order-kline-payload")',
            'getElementById("strategy-order-drilldown-payload")',
        )
    )


def _ordered_symbols(orders: pd.DataFrame, case_id: str | None) -> list[str]:
    if orders.empty:
        return []
    frame = orders.copy()
    if case_id and "case_id" in frame.columns:
        frame = frame[frame["case_id"] == case_id].copy()
    if "symbol" not in frame.columns:
        return []
    frame["symbol"] = frame["symbol"].map(lambda value: normalize_symbol(str(value)))
    return sorted(frame["symbol"].dropna().astype(str).unique())


def _default_strategy_account_href(case_id: str | None) -> str:
    return f"strategy_account_viewer_{case_id}.html" if case_id else "strategy_account_viewer.html"


def _has_symbol_bars(bars: pd.DataFrame, symbol: str) -> bool:
    if bars.empty or "symbol" not in bars.columns:
        return False
    normalized = bars["symbol"].map(lambda value: normalize_symbol(str(value)))
    return bool((normalized == symbol).any())
