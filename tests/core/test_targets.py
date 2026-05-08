import pandas as pd
import pytest

from backtest.core.targets import TARGET_PORTFOLIO_COLUMNS, validate_target_portfolio_frame


def test_validate_target_portfolio_frame_normalizes_and_sorts():
    raw = pd.DataFrame(
        {
            "timestamp": ["2025-01-02", "2025-01-02"],
            "instrument_id": ["aapl.us", "00700.hk"],
            "target_weight": [0.3, 0.2],
        }
    )

    result = validate_target_portfolio_frame(raw)

    assert list(result.columns) == TARGET_PORTFOLIO_COLUMNS
    assert result["instrument_id"].tolist() == ["00700.HK", "AAPL.US"]
    assert result["target_weight"].tolist() == [0.2, 0.3]


def test_validate_target_portfolio_frame_rejects_daily_weight_sum_above_one():
    raw = pd.DataFrame(
        {
            "timestamp": ["2025-01-02", "2025-01-02"],
            "instrument_id": ["AAPL.US", "MSFT.US"],
            "target_weight": [0.7, 0.4],
        }
    )

    with pytest.raises(ValueError, match="target weight sum"):
        validate_target_portfolio_frame(raw)


def test_validate_target_portfolio_frame_rejects_duplicate_timestamp_instrument():
    raw = pd.DataFrame(
        {
            "timestamp": ["2025-01-02", "2025-01-02"],
            "instrument_id": ["AAPL.US", "AAPL.US"],
            "target_weight": [0.2, 0.3],
        }
    )

    with pytest.raises(ValueError, match="duplicate"):
        validate_target_portfolio_frame(raw)
