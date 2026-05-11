from pathlib import Path

import pandas as pd

from backtest.charts import build_strategy_account_payload, write_strategy_account_viewer


def test_build_strategy_account_payload_reconstructs_position_values():
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(
                [
                    "2025-01-02",
                    "2025-01-02",
                    "2025-01-03",
                    "2025-01-03",
                    "2025-01-06",
                    "2025-01-06",
                ]
            ),
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
        max_position_symbols=1,
    )

    assert payload["case_id"] == "case_a"
    assert [point["return"] for point in payload["account_curve"]] == [0.0, 0.01, 0.03]
    series = {item["symbol"]: item["points"] for item in payload["position_value_series"]}
    assert [point["market_value"] for point in series["000001.SZ"]] == [1050.0, 1100.0, 720.0]
    assert [point["market_value"] for point in series["Other"]] == [0.0, 1050.0, 1100.0]
    assert [item["members"] for item in payload["position_value_series"] if item["symbol"] == "Other"] == [
        ["600000.SH"]
    ]
    assert [order["order_id"] for order in payload["orders"]] == ["order-000000", "order-000001", "order-000002"]
    assert payload["links"]["order_drilldown"] == "strategy_order_drilldown_case_a.html"
    assert payload["orders"][2]["fee_total"] == 1.6
    assert payload["summary"]["order_count"] == 3
    assert payload["summary"]["filled_order_count"] == 3
    assert payload["summary"]["symbol_count"] == 2
    assert payload["summary"]["total_return"] == 0.03


def test_build_strategy_account_payload_expands_positions_by_default():
    symbols = [f"300{index:03d}.SZ" for index in range(1, 22)]
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02"] * len(symbols)),
            "symbol": symbols,
            "close": [float(index) for index in range(1, len(symbols) + 1)],
        }
    )
    orders = pd.DataFrame(
        {
            "case_id": ["case_a"] * len(symbols),
            "date": pd.to_datetime(["2025-01-02"] * len(symbols)),
            "symbol": symbols,
            "side": ["buy"] * len(symbols),
            "filled_shares": [100] * len(symbols),
            "price": [float(index) for index in range(1, len(symbols) + 1)],
            "commission": [0.0] * len(symbols),
            "tax": [0.0] * len(symbols),
            "transfer_fee": [0.0] * len(symbols),
            "slippage_cost": [0.0] * len(symbols),
            "status": ["filled"] * len(symbols),
            "reason": [""] * len(symbols),
        }
    )
    equity = pd.DataFrame(
        {
            "case_id": ["case_a"],
            "date": pd.to_datetime(["2025-01-02"]),
            "equity": [100000.0],
            "cash": [97000.0],
        }
    )

    payload = build_strategy_account_payload(bars=bars, orders=orders, equity_curve=equity, case_id="case_a")

    assert len(payload["position_value_series"]) == 21
    assert [series["symbol"] for series in payload["position_value_series"][:2]] == ["300021.SZ", "300020.SZ"]
    assert all(series["symbol"] != "Other" for series in payload["position_value_series"])


def test_write_strategy_account_viewer_embeds_account_sections(tmp_path: Path):
    payload = {
        "title": "Strategy Account Viewer",
        "case_id": "case_a",
        "account_curve": [
            {"date": "2025-01-02", "equity": 100000.0, "cash": 99000.0, "return": 0.0},
            {"date": "2025-01-03", "equity": 101000.0, "cash": 98000.0, "return": 0.01},
        ],
        "position_value_series": [
            {
                "symbol": "000001.SZ",
                "points": [
                    {"date": "2025-01-01", "shares": 0.0, "market_value": 0.0},
                    {"date": "2025-01-02", "shares": 100.0, "market_value": 1050.0},
                    {"date": "2025-01-03", "shares": 100.0, "market_value": 1100.0},
                ],
            },
            {
                "symbol": "Other",
                "members": ["600000.SH", "300001.SZ"],
                "points": [
                    {"date": "2025-01-01", "shares": 0.0, "market_value": 0.0},
                    {"date": "2025-01-02", "shares": 0.0, "market_value": 500.0},
                    {"date": "2025-01-03", "shares": 0.0, "market_value": 700.0},
                ],
            }
        ],
        "orders": [
            {
                "date": "2025-01-02",
                "order_id": "order-000000",
                "symbol": "000001.SZ",
                "side": "buy",
                "filled_shares": 100.0,
                "price": 10.2,
                "fee_total": 1.1,
                "notional": 1020.0,
                "status": "filled",
                "reason": "",
            }
        ],
        "summary": {
            "start_date": "2025-01-02",
            "end_date": "2025-01-03",
            "symbol_count": 1,
            "order_count": 1,
            "filled_order_count": 1,
            "initial_equity": 100000.0,
            "latest_equity": 101000.0,
            "latest_cash": 98000.0,
            "total_return": 0.01,
        },
        "links": {
            "order_drilldown": "strategy_order_drilldown_case_a.html",
            "result_catalog": "strategy_results_index.html",
        },
        "metadata": {},
    }
    output_path = tmp_path / "strategy_account_viewer.html"

    write_strategy_account_viewer(payload, output_path)

    html = output_path.read_text(encoding="utf-8")
    assert "strategy-account-payload" in html
    assert "Strategy Account Viewer" in html
    assert "Holdings Value" in html
    assert "Equity/Cash" in html
    assert "Return" in html
    assert '<div class="panel-header"><h2>Holdings Value</h2></div>' in html
    assert '<div class="panel-header"><h2>Equity/Cash</h2></div>' in html
    assert '<div class="panel-header"><h2>Return</h2></div>' in html
    assert "annotations:" not in html
    assert "text: title" not in html
    assert "Position Market Value" not in html
    assert "Account Equity / Cash" not in html
    assert "Strategy Return" not in html
    assert "plotPointValue" not in html
    assert "curveLabelAnnotations" not in html
    assert "Other includes" not in html
    assert "market value:" not in html
    assert "%{x}<br>Return" not in html
    assert "%{x}<br>" not in html
    assert "function positiveMarketValue" in html
    assert "const positionLineTraces" in html
    assert "const positionHoverTraces" in html
    assert "const HOLDINGS_LEGEND_ROWS = 3;" in html
    assert "const HOLDINGS_LEGEND_ITEM_WIDTH = 132;" in html
    assert "function holdingsLegendPageSize" in html
    assert "return HOLDINGS_LEGEND_ROWS * columns;" in html
    assert "const pageSize = holdingsLegendPageSize();" in html
    assert "window.addEventListener(\"resize\", () => {" in html
    assert 'id="holdingsLegend"' in html
    assert 'id="holdingsLegendPrev"' in html
    assert 'id="holdingsLegendNext"' in html
    assert 'id="holdingsLegendPage"' in html
    assert "renderHoldingsLegend" in html
    assert "togglePositionSeries" in html
    assert "let holdingsLegendClickTimer = null;" in html
    assert "function handleHoldingsLegendClick" in html
    assert "function handleHoldingsLegendDoubleClick" in html
    assert "function isolatePositionSeries" in html
    assert "function showAllPositionSeries" in html
    assert "activePositionSymbols.size === 1 && activePositionSymbols.has(symbol)" in html
    assert "window.setTimeout" in html
    assert "window.clearTimeout(holdingsLegendClickTimer)" in html
    assert 'addEventListener("click", handleHoldingsLegendClick)' in html
    assert 'addEventListener("dblclick", handleHoldingsLegendDoubleClick)' in html
    assert 'hoverinfo: "skip"' in html
    assert "y: series.points.map((point) => positiveMarketValue(point.market_value))" in html
    assert "line: { color: traceColor(index), width: 2 }" in html
    assert "width: 0.1" not in html
    assert "const positionTraces = positionLineTraces.concat(positionHoverTraces);" in html
    assert html.count("hovertemplate") == 2
    assert 'hovertemplate: `${series.symbol} : %{y:~s}<extra></extra>`' in html
    assert 'hovertemplate: "Return : %{y:.2%}<extra></extra>"' in html
    assert "hoverformat: yTickFormat" in html
    assert "showlegend: false" in html
    assert 'id="holdingsChart"' in html
    assert 'id="accountChart"' in html
    assert 'id="returnChart"' in html
    assert "legend2" not in html
    assert "legend3" not in html
    assert '"holdingsChart",' in html
    assert 'Plotly.newPlot("accountChart"' in html
    assert 'Plotly.newPlot("returnChart"' in html
    assert "const returnTrace" in html
    assert 'Plotly.newPlot("accountChart", accountTraces' in html
    assert 'Plotly.newPlot("returnChart", [returnTrace]' in html
    assert "matches: \"x\"" not in html
    assert "showticklabels: false" not in html
    assert "y: series.points.map((point) => point.market_value)" in html
    assert "Order List" in html
    assert "orderDrilldownHref" in html
    assert "buildOrderDrilldownHref" in html
    assert "strategy_order_drilldown_case_a.html" in html
    assert 'id="strategyResultsLink"' in html
    assert "Back to Results Catalog" in html
    assert "strategy_results_index.html" in html
    assert "strategyResultsHref" in html
    assert 'params.set("symbol", order.symbol)' in html
    assert 'params.set("order_id", order.order_id)' in html
    assert "data-order-id" in html
    assert "data-symbol" in html
    assert "data-drilldown-href" in html
    assert "000001.SZ" in html
    assert html.count("Plotly.newPlot") == 3
