from pathlib import Path

import pandas as pd

from backtest.charts.strategy_order_drilldown_viewer import (
    build_strategy_order_drilldown_payload,
    write_strategy_order_drilldown_viewer,
)


def test_build_strategy_order_drilldown_payload_groups_symbols_and_orders():
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-02", "2025-01-03"]),
            "symbol": ["000001.SZ", "000001.SZ", "600000.SH", "600000.SH"],
            "open": [10.0, 10.5, 20.0, 20.5],
            "high": [11.0, 11.2, 21.0, 21.2],
            "low": [9.8, 10.1, 19.8, 20.1],
            "close": [10.5, 10.8, 20.5, 20.8],
            "volume": [1000, 1200, 1400, 1600],
            "amount": [10500.0, 12960.0, 28700.0, 33280.0],
        }
    )
    orders = pd.DataFrame(
        {
            "case_id": ["case_a", "case_a", "case_a", "case_b"],
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-03", "2025-01-03"]),
            "symbol": ["000001.SZ", "000001.SZ", "600000.SH", "000001.SZ"],
            "side": ["buy", "sell", "buy", "buy"],
            "requested_shares": [100, 100, 50, 999],
            "filled_shares": [100, 100, 50, 999],
            "price": [10.2, 10.7, 20.6, 10.6],
            "commission": [5.0, 5.0, 5.0, 5.0],
            "tax": [0.0, 1.0, 0.0, 0.0],
            "transfer_fee": [0.1, 0.1, 0.1, 0.1],
            "slippage_cost": [0.0, 0.0, 0.0, 0.0],
            "status": ["filled", "filled", "filled", "filled"],
            "reason": ["", "", "", ""],
        }
    )
    equity = pd.DataFrame(
        {
            "case_id": ["case_a", "case_a"],
            "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "equity": [100000.0, 100500.0],
            "cash": [99000.0, 100500.0],
        }
    )

    payload = build_strategy_order_drilldown_payload(
        bars=bars,
        orders=orders,
        equity_curve=equity,
        case_id="case_a",
        default_symbol="600000.SH",
    )

    assert payload["case_id"] == "case_a"
    assert payload["default_symbol"] == "600000.SH"
    assert payload["links"]["strategy_account"] == "strategy_account_viewer_case_a.html"
    assert [item["symbol"] for item in payload["symbols"]] == ["000001.SZ", "600000.SH"]
    by_symbol = {item["symbol"]: item for item in payload["symbols"]}
    assert [order["order_id"] for order in by_symbol["000001.SZ"]["orders"]] == [
        "order-000000",
        "order-000001",
    ]
    assert [order["order_id"] for order in by_symbol["600000.SH"]["orders"]] == ["order-000002"]
    assert payload["summary"]["symbol_count"] == 2
    assert payload["summary"]["order_count"] == 3


def test_write_strategy_order_drilldown_viewer_supports_hash_order_navigation(tmp_path: Path):
    payload = {
        "title": "Strategy Order Drilldown",
        "case_id": "case_a",
        "default_symbol": "000001.SZ",
        "symbols": [
            {
                "symbol": "000001.SZ",
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
                        "symbol": "000001.SZ",
                        "side": "buy",
                        "filled_shares": 100,
                        "price": 10.2,
                        "fee_total": 1.1,
                        "status": "filled",
                        "reason": "",
                        "position_after": 100,
                        "realized_pnl": 0.0,
                        "realized_return": 0.0,
                    }
                ],
                "summary": {"order_count": 1, "total_return": 0.0},
            }
        ],
        "links": {"strategy_account": "strategy_account_viewer_case_a.html"},
        "summary": {"symbol_count": 1, "order_count": 1},
        "metadata": {},
    }
    output_path = tmp_path / "strategy_order_drilldown.html"

    write_strategy_order_drilldown_viewer(payload, output_path)

    html = output_path.read_text(encoding="utf-8")
    assert "strategy-order-drilldown-payload" in html
    assert "Strategy Order Drilldown" in html
    assert 'id="strategyResultLink"' in html
    assert "Back to Account Viewer" in html
    assert "strategy_account_viewer_case_a.html" in html
    assert "strategyResultHref" in html
    assert 'id="symbolSelect"' in html
    assert "readRoute" in html
    assert "writeRoute" in html
    assert "applyRoute" in html
    assert "focusOrder" in html
    assert "activeOrderId" in html
    assert "order-row-active" in html
    assert "data-order-id" in html
    assert "orderRows.addEventListener" in html
    assert "window.addEventListener(\"hashchange\", applyRoute)" in html
    assert "Plotly.newPlot" in html
