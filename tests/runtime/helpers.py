import pandas as pd

from backtest.config.models import ExecutionConfig
from backtest.core.enums import ExecutionTiming


def bars(
    dates: list[str],
    opens: list[float],
    closes: list[float],
    *,
    symbol: str | list[str] = "000001.SZ",
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    volumes: list[float] | None = None,
    is_suspended: list[bool] | None = None,
    limit_up: list[float] | None = None,
    limit_down: list[float] | None = None,
) -> pd.DataFrame:
    highs = highs or [max(open_value, close_value) + 1 for open_value, close_value in zip(opens, closes, strict=True)]
    lows = lows or [min(open_value, close_value) - 1 for open_value, close_value in zip(opens, closes, strict=True)]
    volumes = volumes or [1000.0] * len(dates)
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "symbol": symbol if isinstance(symbol, list) else [symbol] * len(dates),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "amount": [close * volume for close, volume in zip(closes, volumes, strict=True)],
            "frequency": ["1d"] * len(dates),
            "adjust": ["qfq"] * len(dates),
        }
    )
    if is_suspended is not None:
        frame["is_suspended"] = is_suspended
    if limit_up is not None:
        frame["limit_up"] = limit_up
    if limit_down is not None:
        frame["limit_down"] = limit_down
    return frame


def execution_config() -> ExecutionConfig:
    return ExecutionConfig(
        timing=ExecutionTiming.NEXT_OPEN,
        initial_cash=100000.0,
        commission_rate=0.0003,
        min_commission=5.0,
        stamp_tax_rate=0.0005,
        transfer_fee_rate=0.00001,
        slippage_rate=0.0,
        board_lot_size=100,
    )
