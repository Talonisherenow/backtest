from pathlib import Path

import pandas as pd

from backtest.charts.strategy_results_service import StrategyResultsService
from backtest.data.store import ParquetBarStore


def _write_run(root: Path) -> None:
    root.mkdir(parents=True)
    (root / "summary.csv").write_text(
        "\n".join(
            [
                "case,signal_id,signal_slug,holding_days,backend,planning_mode,symbols,bars,total_return,max_drawdown,sharpe_ratio,orders,filled_orders,rejected_orders",
                "buy_signal_02_rising_price_pullback_hold_20,2,02_rising_price_pullback,20,native_simulation,batch,1,2,0.052,-0.083,0.42,2,2,0",
            ]
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "case_id": ["signal_02_hold_20", "signal_02_hold_20"],
            "case": [
                "buy_signal_02_rising_price_pullback_hold_20",
                "buy_signal_02_rising_price_pullback_hold_20",
            ],
            "signal_id": [2, 2],
            "holding_days": [20, 20],
            "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "symbol": ["000001.SZ", "000001.SZ"],
            "side": ["buy", "sell"],
            "requested_shares": [100, 100],
            "filled_shares": [100, 100],
            "price": [10.0, 10.8],
            "commission": [1.0, 1.0],
            "tax": [0.0, 0.5],
            "transfer_fee": [0.1, 0.1],
            "slippage_cost": [0.0, 0.0],
            "status": ["filled", "filled"],
            "reason": ["", ""],
        }
    ).to_csv(root / "orders.csv", index=False)
    pd.DataFrame(
        {
            "case_id": ["signal_02_hold_20", "signal_02_hold_20"],
            "case": [
                "buy_signal_02_rising_price_pullback_hold_20",
                "buy_signal_02_rising_price_pullback_hold_20",
            ],
            "signal_id": [2, 2],
            "holding_days": [20, 20],
            "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "equity": [100000.0, 100080.0],
            "cash": [99000.0, 100080.0],
        }
    ).to_csv(root / "equity_curve.csv", index=False)


def _write_bars(root: Path) -> None:
    ParquetBarStore(root).write_bars(
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
                "symbol": ["000001.SZ", "000001.SZ"],
                "open": [10.0, 10.5],
                "high": [10.5, 11.0],
                "low": [9.8, 10.1],
                "close": [10.2, 10.8],
                "volume": [1000, 1200],
                "amount": [10200.0, 12960.0],
                "frequency": ["1d", "1d"],
                "adjust": ["qfq", "qfq"],
            }
        )
    )


def test_strategy_results_service_discovers_catalog_and_builds_details(tmp_path: Path):
    run_root = tmp_path / "runs" / "new_runtime"
    bars_root = tmp_path / "bars"
    _write_run(run_root)
    _write_bars(bars_root)

    service = StrategyResultsService(results_roots=[run_root], bars_root=bars_root)

    catalog = service.catalog()
    assert catalog["summary"] == {"strategy_count": 1, "result_count": 1}
    result = catalog["strategies"][0]["results"][0]
    assert result["case_id"] == "signal_02_hold_20"
    assert result["detail_href"] == "/strategy-results/account?case_id=signal_02_hold_20"

    account = service.account_payload("signal_02_hold_20")
    assert account["case_id"] == "signal_02_hold_20"
    assert account["links"]["result_catalog"] == "/strategy-results"
    assert account["links"]["order_drilldown"] == "/strategy-results/drilldown?case_id=signal_02_hold_20"
    assert account["summary"]["order_count"] == 2

    drilldown = service.drilldown_payload("signal_02_hold_20", default_symbol="000001.SZ")
    assert drilldown["case_id"] == "signal_02_hold_20"
    assert drilldown["default_symbol"] == "000001.SZ"
    assert drilldown["links"]["strategy_account"] == "/strategy-results/account?case_id=signal_02_hold_20"
