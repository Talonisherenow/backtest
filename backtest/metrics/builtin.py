from collections.abc import Callable, Iterable
import math

import pandas as pd

from backtest.metrics.context import BacktestResultContext

TRADING_DAYS_PER_YEAR = 252


def calculate_builtin_metrics(
    context: BacktestResultContext,
    names: Iterable[str],
) -> dict[str, float]:
    available: dict[str, Callable[[], float]] = {
        "total_return": lambda: _total_return(context.equity_curve),
        "annualized_return": lambda: _annualized_return(context.equity_curve),
        "annualized_volatility": lambda: _annualized_volatility(context.equity_curve),
        "max_drawdown": lambda: _max_drawdown(context.equity_curve),
        "sharpe_ratio": lambda: _sharpe_ratio(context.equity_curve),
        "trade_count": lambda: _trade_count(context.trades),
        "cash_ratio": lambda: _cash_ratio(context.equity_curve),
    }

    return {
        name: _normalized_float(available[name]())
        for name in names
        if name in available
    }


def _equity_series(equity_curve: object) -> pd.Series:
    if equity_curve is None:
        return pd.Series(dtype="float64")
    if isinstance(equity_curve, pd.Series):
        raw = equity_curve
    elif isinstance(equity_curve, pd.DataFrame) and "equity" in equity_curve:
        raw = equity_curve["equity"]
    else:
        return pd.Series(dtype="float64")

    return pd.to_numeric(raw, errors="coerce").dropna().astype("float64")


def _returns(equity_curve: object) -> pd.Series:
    equity = _equity_series(equity_curve)
    if len(equity) < 2:
        return pd.Series(dtype="float64")
    return equity.pct_change().replace([math.inf, -math.inf], math.nan).dropna()


def _total_return(equity_curve: object) -> float:
    equity = _equity_series(equity_curve)
    if len(equity) < 2:
        return 0.0
    first = float(equity.iloc[0])
    if first == 0.0:
        return 0.0
    return float(equity.iloc[-1] / first - 1.0)


def _annualized_return(equity_curve: object) -> float:
    equity = _equity_series(equity_curve)
    if len(equity) < 2:
        return 0.0
    first = float(equity.iloc[0])
    last = float(equity.iloc[-1])
    if first <= 0.0 or last <= 0.0:
        return 0.0
    years = (len(equity) - 1) / TRADING_DAYS_PER_YEAR
    if years <= 0.0:
        return 0.0
    return float((last / first) ** (1.0 / years) - 1.0)


def _annualized_volatility(equity_curve: object) -> float:
    returns = _returns(equity_curve)
    if len(returns) < 2:
        return 0.0
    return float(returns.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))


def _max_drawdown(equity_curve: object) -> float:
    equity = _equity_series(equity_curve)
    if len(equity) < 2:
        return 0.0
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    drawdown = drawdown.replace([math.inf, -math.inf], math.nan).dropna()
    if drawdown.empty:
        return 0.0
    return float(drawdown.min())


def _sharpe_ratio(equity_curve: object) -> float:
    returns = _returns(equity_curve)
    if len(returns) < 2:
        return 0.0
    volatility = float(returns.std(ddof=1))
    if volatility == 0.0:
        return 0.0
    return float(returns.mean() / volatility * math.sqrt(TRADING_DAYS_PER_YEAR))


def _trade_count(trades: object) -> float:
    if trades is None:
        return 0.0
    try:
        return float(len(trades))  # type: ignore[arg-type]
    except TypeError:
        return 0.0


def _cash_ratio(equity_curve: object) -> float:
    if not isinstance(equity_curve, pd.DataFrame):
        return 0.0
    if "cash" not in equity_curve or "equity" not in equity_curve:
        return 0.0

    if equity_curve.empty:
        return 0.0

    latest = equity_curve.iloc[-1]
    cash = pd.to_numeric(pd.Series([latest["cash"]]), errors="coerce").iloc[0]
    equity = pd.to_numeric(pd.Series([latest["equity"]]), errors="coerce").iloc[0]
    if pd.isna(cash) or pd.isna(equity):
        return 0.0

    last_equity = float(equity)
    if last_equity == 0.0:
        return 0.0
    return float(cash / last_equity)


def _normalized_float(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return round(value, 12)
