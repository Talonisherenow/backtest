from pathlib import Path

import pandas as pd

from backtest.charts.strategy_results_catalog import (
    build_strategy_results_catalog_payload,
    write_strategy_results_catalog,
)


def test_build_strategy_results_catalog_payload_groups_ten_buy_signal_cases():
    summary = pd.DataFrame(
        [
            {
                "case": "buy_signal_02_rising_price_pullback_hold_1",
                "signal_id": 2,
                "signal_slug": "02_rising_price_pullback",
                "holding_days": 1,
                "backend": "native_simulation",
                "planning_mode": "batch",
                "symbols": 100,
                "bars": 30000,
                "total_return": -0.071,
                "max_drawdown": -0.115,
                "sharpe_ratio": -1.33,
                "orders": 242,
                "filled_orders": 242,
                "rejected_orders": 0,
            },
            {
                "case": "buy_signal_02_rising_price_pullback_hold_20",
                "signal_id": 2,
                "signal_slug": "02_rising_price_pullback",
                "holding_days": 20,
                "backend": "native_simulation",
                "planning_mode": "batch",
                "symbols": 100,
                "bars": 30000,
                "total_return": 0.052,
                "max_drawdown": -0.083,
                "sharpe_ratio": 0.42,
                "orders": 163,
                "filled_orders": 120,
                "rejected_orders": 43,
            },
            {
                "case": "buy_signal_03_weekly_volume_contraction_hold_1",
                "signal_id": 3,
                "signal_slug": "03_weekly_volume_contraction",
                "holding_days": 1,
                "backend": "native_simulation",
                "planning_mode": "batch",
                "symbols": 100,
                "bars": 30000,
                "total_return": 0.03,
                "max_drawdown": -0.049,
                "sharpe_ratio": 0.58,
                "orders": 142,
                "filled_orders": 142,
                "rejected_orders": 0,
            },
        ]
    )

    payload = build_strategy_results_catalog_payload(summary_frames=[summary])

    assert payload["summary"] == {"strategy_count": 2, "result_count": 3}
    assert [item["strategy_id"] for item in payload["strategies"]] == ["signal_02", "signal_03"]
    signal_02 = payload["strategies"][0]
    assert signal_02["slug"] == "rising_price_pullback"
    assert signal_02["name"] == "Rising Price Pullback"
    assert signal_02["result_count"] == 2
    assert signal_02["best_total_return"] == 0.052
    assert [result["holding_days"] for result in signal_02["results"]] == [1, 20]
    assert signal_02["results"][1]["result_id"] == "buy_signal_02_rising_price_pullback_hold_20"
    assert signal_02["results"][1]["case_id"] == "signal_02_hold_20"
    assert signal_02["results"][1]["detail_href"] == "strategy_account_viewer_signal_02_hold_20.html"


def test_write_strategy_results_catalog_renders_strategy_and_result_links(tmp_path: Path):
    payload = {
        "title": "Strategy Results",
        "generated_at": "2026-05-10T22:30:00+08:00",
        "strategies": [
            {
                "strategy_id": "signal_02",
                "name": "Rising Price Pullback",
                "slug": "rising_price_pullback",
                "source_type": "ten_buy_signal",
                "implementation": "signal_slug:02_rising_price_pullback",
                "result_count": 1,
                "best_total_return": 0.052,
                "latest_run_at": "",
                "results": [
                    {
                        "result_id": "buy_signal_02_rising_price_pullback_hold_20",
                        "case_id": "buy_signal_02_rising_price_pullback_hold_20",
                        "strategy_id": "signal_02",
                        "run_group": "summary",
                        "holding_days": 20,
                        "backend": "native_simulation",
                        "planning_mode": "batch",
                        "symbols": 100,
                        "bars": 30000,
                        "start_date": "",
                        "end_date": "",
                        "total_return": 0.052,
                        "max_drawdown": -0.083,
                        "sharpe_ratio": 0.42,
                        "orders": 163,
                        "filled_orders": 120,
                        "rejected_orders": 43,
                        "detail_href": "strategy_account_viewer_buy_signal_02_rising_price_pullback_hold_20.html",
                        "legacy_report_href": "",
                    }
                ],
            }
        ],
        "summary": {"strategy_count": 1, "result_count": 1},
        "metadata": {},
    }
    output = tmp_path / "strategy_results_index.html"

    write_strategy_results_catalog(payload, output)

    html = output.read_text(encoding="utf-8")
    assert "strategy-results-catalog-payload" in html
    assert "Strategy Results" in html
    assert "signal_02" in html
    assert "rising_price_pullback" in html
    assert "strategy_account_viewer_buy_signal_02_rising_price_pullback_hold_20.html" in html
    assert "function renderStrategies" in html
    assert "function renderResults" in html
    assert "data-detail-href" in html
    assert "resultRows.addEventListener" in html
    assert 'id="strategySearch"' in html


def test_render_strategy_results_catalog_dynamic_shell_fetches_api():
    from backtest.charts.strategy_results_catalog import render_strategy_results_catalog_html

    html = render_strategy_results_catalog_html(
        {
            "mode": "dynamic",
            "title": "Strategy Results",
            "links": {"workbench_home": "/"},
        }
    )

    assert "strategy-results-catalog-payload" in html
    assert 'fetch("/api/strategy-results")' in html
    assert "Loading strategy results" in html
    assert 'id="workbenchHomeLink"' in html
    assert "Workbench Home" in html
    assert "workbenchHomeHref" in html
    assert 'id="dataSourceMonitor"' not in html
    assert 'id="dataSourceDrawer"' not in html
    assert 'fetch(dataApiUrl("/api/data-sources")' not in html
