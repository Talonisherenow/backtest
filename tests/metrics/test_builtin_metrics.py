import math

import pandas as pd

from backtest.metrics import BacktestResultContext, calculate_builtin_metrics


def make_context(equity_curve: pd.DataFrame) -> BacktestResultContext:
    return BacktestResultContext(
        equity_curve=equity_curve,
        positions=pd.DataFrame(),
        trades=pd.DataFrame(),
        orders=pd.DataFrame(),
        bars=pd.DataFrame(),
        config={},
    )


def test_total_return_and_max_drawdown_from_equity_curve() -> None:
    context = make_context(pd.DataFrame({"equity": [100.0, 110.0, 99.0]}))

    metrics = calculate_builtin_metrics(context, ["total_return", "max_drawdown"])

    assert metrics["total_return"] == -0.01
    assert metrics["max_drawdown"] == -0.10


def test_empty_and_single_point_equity_return_zero_without_nan() -> None:
    metric_names = [
        "total_return",
        "annualized_return",
        "annualized_volatility",
        "max_drawdown",
        "sharpe_ratio",
        "cash_ratio",
    ]

    empty_metrics = calculate_builtin_metrics(
        make_context(pd.DataFrame({"equity": []})),
        metric_names,
    )
    single_point_metrics = calculate_builtin_metrics(
        make_context(pd.DataFrame({"equity": [100.0]})),
        metric_names,
    )

    assert empty_metrics == {name: 0.0 for name in metric_names}
    assert single_point_metrics == {name: 0.0 for name in metric_names}
    assert all(math.isfinite(value) for value in empty_metrics.values())
    assert all(math.isfinite(value) for value in single_point_metrics.values())


def test_cash_ratio_trade_count_sharpe_handle_missing_and_zero_volatility() -> None:
    context = BacktestResultContext(
        equity_curve=pd.DataFrame({"equity": [100.0, 100.0, 100.0]}),
        positions=pd.DataFrame(),
        trades=pd.DataFrame({"symbol": ["000001.SZ", "000002.SZ"]}),
        orders=pd.DataFrame(),
        bars=pd.DataFrame(),
        config={},
    )

    metrics = calculate_builtin_metrics(
        context,
        ["cash_ratio", "trade_count", "sharpe_ratio", "unknown_metric"],
    )

    assert metrics == {
        "cash_ratio": 0.0,
        "trade_count": 2.0,
        "sharpe_ratio": 0.0,
    }


def test_cash_ratio_uses_latest_row_without_mixing_stale_cash() -> None:
    context = make_context(pd.DataFrame({"equity": [100.0, 200.0], "cash": [50.0, None]}))

    metrics = calculate_builtin_metrics(context, ["cash_ratio"])

    assert metrics["cash_ratio"] == 0.0


def test_return_metrics_use_config_initial_cash_as_baseline() -> None:
    context = BacktestResultContext(
        equity_curve=pd.DataFrame({"equity": [99995.0, 99995.0]}),
        positions=pd.DataFrame(),
        trades=pd.DataFrame(),
        orders=pd.DataFrame(),
        bars=pd.DataFrame(),
        config={"execution": {"initial_cash": 100000.0}},
    )

    metrics = calculate_builtin_metrics(context, ["total_return", "max_drawdown"])

    assert metrics["total_return"] == -0.00005
    assert metrics["max_drawdown"] == -0.00005
