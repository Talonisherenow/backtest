import pandas as pd
import pytest

from backtest.core.frames import validate_bar_frame, validate_signal_frame


def _valid_bar_frame(**overrides):
    data = {
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
    data.update(overrides)
    return pd.DataFrame(data)


def test_validate_bar_frame_normalizes_columns_and_symbols():
    raw = _valid_bar_frame()

    result = validate_bar_frame(raw)

    assert result.loc[0, "symbol"] == "000001.SZ"
    assert str(result.loc[0, "date"].date()) == "2025-01-02"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"date": [None]}, "required values"),
        ({"amount": [None]}, "required values"),
    ],
)
def test_validate_bar_frame_rejects_null_required_values(overrides, message):
    with pytest.raises(ValueError, match=message):
        validate_bar_frame(_valid_bar_frame(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"open": [11.5]},
        {"close": [11.5]},
        {"open": [9.0]},
        {"close": [9.0]},
    ],
)
def test_validate_bar_frame_rejects_invalid_ohlc_relationships(overrides):
    with pytest.raises(ValueError, match="OHLC"):
        validate_bar_frame(_valid_bar_frame(**overrides))


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


@pytest.mark.parametrize(
    "raw",
    [
        pd.DataFrame(
            {
                "date": [None],
                "symbol": ["000001.SZ"],
                "target_weight": [0.20],
            }
        ),
        pd.DataFrame(
            {
                "date": ["2025-01-02"],
                "symbol": ["000001.SZ"],
                "target_weight": [None],
            }
        ),
    ],
)
def test_validate_signal_frame_rejects_null_required_values(raw):
    with pytest.raises(ValueError, match="required values"):
        validate_signal_frame(raw)


def test_validate_signal_frame_rejects_duplicate_date_symbol_rows():
    raw = pd.DataFrame(
        {
            "date": ["2025-01-02", "2025-01-02"],
            "symbol": ["000001.SZ", "000001.SZ"],
            "target_weight": [0.20, 0.30],
        }
    )

    with pytest.raises(ValueError, match="duplicate"):
        validate_signal_frame(raw)
