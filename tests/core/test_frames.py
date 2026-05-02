import pandas as pd
import pytest

from backtest.core.frames import validate_bar_frame, validate_signal_frame


def test_validate_bar_frame_normalizes_columns_and_symbols():
    raw = pd.DataFrame(
        {
            "date": ["2025-01-02"],
            "symbol": ["000001"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.5],
            "close": [10.5],
            "volume": [1000],
            "amount": [10500.0],
            "frequency": ["1d"],
            "adjust": ["qfq"],
        }
    )

    result = validate_bar_frame(raw)

    assert result.loc[0, "symbol"] == "000001.SZ"
    assert str(result.loc[0, "date"].date()) == "2025-01-02"


def test_validate_signal_frame_rejects_weight_sum_above_one():
    raw = pd.DataFrame(
        {
            "date": ["2025-01-02", "2025-01-02"],
            "symbol": ["000001.SZ", "600519.SH"],
            "target_weight": [0.70, 0.40],
        }
    )

    with pytest.raises(ValueError, match="target weight sum"):
        validate_signal_frame(raw, stock_pool=["000001.SZ", "600519.SH"])


def test_validate_signal_frame_rejects_symbol_outside_pool():
    raw = pd.DataFrame(
        {
            "date": ["2025-01-02"],
            "symbol": ["600519.SH"],
            "target_weight": [0.20],
        }
    )

    with pytest.raises(ValueError, match="outside stock pool"):
        validate_signal_frame(raw, stock_pool=["000001.SZ"])
