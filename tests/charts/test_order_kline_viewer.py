from pathlib import Path

import pandas as pd
import pytest

from backtest.charts.order_kline_viewer import (
    build_order_kline_payload,
    write_order_kline_viewer,
)


def test_build_order_kline_payload_filters_symbol_and_case_with_account_curves():
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            "symbol": ["000001.SZ", "000001.SZ", "600000.SH"],
            "open": [10.0, 10.5, 20.0],
            "high": [11.0, 11.2, 21.0],
            "low": [9.8, 10.1, 19.5],
            "close": [10.5, 10.8, 20.5],
            "volume": [1000, 1200, 1400],
            "amount": [10500.0, 12960.0, 28700.0],
        }
    )
    orders = pd.DataFrame(
        {
            "case_id": ["case_a", "case_a", "case_b"],
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-03"]),
            "symbol": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "side": ["buy", "sell", "buy"],
            "requested_shares": [100, 100, 200],
            "filled_shares": [100, 100, 200],
            "price": [10.2, 10.7, 10.6],
            "commission": [5.0, 5.0, 5.0],
            "tax": [0.0, 1.0, 0.0],
            "transfer_fee": [0.1, 0.1, 0.2],
            "slippage_cost": [0.0, 0.0, 0.0],
            "status": ["filled", "filled", "filled"],
            "reason": ["", "", ""],
        }
    )
    equity = pd.DataFrame(
        {
            "case_id": ["case_a", "case_a", "case_b"],
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-03"]),
            "equity": [100000.0, 100500.0, 99000.0],
            "cash": [99000.0, 100500.0, 98000.0],
        }
    )

    payload = build_order_kline_payload(
        bars=bars,
        orders=orders,
        equity_curve=equity,
        symbol="000001.SZ",
        case_id="case_a",
    )

    assert payload["symbol"] == "000001.SZ"
    assert payload["case_id"] == "case_a"
    assert [bar["date"] for bar in payload["bars"]] == ["2025-01-02", "2025-01-03"]
    assert [order["side"] for order in payload["orders"]] == ["buy", "sell"]
    assert payload["orders"][0]["order_id"] == "order-000000"
    assert payload["orders"][1]["order_id"] == "order-000001"
    assert payload["orders"][0]["label"] == "B 10.200"
    assert payload["orders"][1]["label"] == "S 10.700"
    assert payload["orders"][0]["position_after"] == 100.0
    assert payload["orders"][1]["position_after"] == 0.0
    assert payload["orders"][1]["realized_pnl"] == pytest.approx(38.8)
    assert payload["orders"][1]["realized_return"] == pytest.approx(38.8 / 1025.1)
    assert [point["return"] for point in payload["equity_curve"]] == [0.0, 0.005]
    assert payload["summary"]["order_count"] == 2
    assert payload["summary"]["realized_pnl"] == pytest.approx(38.8)
    assert payload["summary"]["total_return"] == 0.005


def test_write_order_kline_viewer_embeds_payload_and_trade_layers(tmp_path: Path):
    payload = {
        "title": "Order K-line Viewer",
        "symbol": "000001.SZ",
        "case_id": "case_a",
        "bars": [
            {
                "date": "2025-01-02",
                "open": 10.0,
                "high": 11.0,
                "low": 9.8,
                "close": 10.5,
                "volume": 1000.0,
                "amount": 10500.0,
            }
        ],
        "orders": [
            {
                "date": "2025-01-02",
                "order_id": "order-000000",
                "side": "buy",
                "filled_shares": 100,
                "price": 10.2,
                "status": "filled",
                "reason": "",
                "position_after": 100,
                "realized_pnl": 0.0,
                "realized_return": 0.0,
            },
            {
                "date": "2025-01-03",
                "order_id": "order-000001",
                "side": "buy",
                "filled_shares": 0,
                "price": 0.0,
                "status": "rejected",
                "reason": "cash insufficient",
                "position_after": 100,
                "realized_pnl": 0.0,
                "realized_return": 0.0,
            }
        ],
        "equity_curve": [
            {
                "date": "2025-01-02",
                "equity": 100000.0,
                "cash": 99000.0,
                "return": 0.0,
            }
        ],
        "summary": {"order_count": 1, "total_return": 0.0},
        "metadata": {},
    }
    output_path = tmp_path / "order_kline_viewer.html"

    write_order_kline_viewer(payload, output_path)

    html = output_path.read_text(encoding="utf-8")
    assert "order-kline-payload" in html
    assert "000001.SZ" in html
    assert "Buy Orders" in html
    assert "Sell Orders" in html
    assert "Volume" in html
    assert 'name: "Equity"' not in html
    assert 'name: "Cash"' not in html
    assert 'name: "Return"' not in html
    assert "Account Equity / Cash" not in html
    assert "Net PnL" in html
    assert "PnL %" in html
    assert "<th>Status</th>" in html
    assert "<th>Reason</th>" in html
    assert "orderLabel" in html
    assert "orderAnnotations" in html
    assert "bgcolor" in html
    assert 'id="windowSizeSelect"' in html
    assert 'id="windowOverlapSelect"' in html
    assert 'id="olderPageButton"' in html
    assert 'id="newerPageButton"' in html
    assert 'id="latestPageButton"' in html
    assert 'id="jumpTimeInput"' in html
    assert 'id="symbolSelect"' in html
    assert 'id="windowSlider"' in html
    assert "visibleBars" in html
    assert "visibleOrders" in html
    assert "function chartOrders" in html
    assert '["filled", "adjusted"].includes(String(order.status || "").toLowerCase())' in html
    assert "Number(order.filled_shares || 0) > 0" in html
    assert "Number(order.price || 0) > 0" in html
    assert "const drawableOrders = chartOrders(windowOrders);" in html
    assert "const buyOrders = drawableOrders.filter" in html
    assert "const sellOrders = drawableOrders.filter" in html
    assert "orderAnnotations(drawableOrders)" in html
    assert "ay: isBuy ? 36 : -36" in html
    assert "ay: isBuy ? -36 : 36" not in html
    assert "readRoute" in html
    assert "writeRoute" in html
    assert "applyRoute" in html
    assert "focusOrder" in html
    assert "activeOrderId" in html
    assert "order-row-active" in html
    assert "data-order-id" in html
    assert "orderRows.addEventListener" in html
    assert "renderOrderRows" in html
    assert "Plotly.newPlot" in html
