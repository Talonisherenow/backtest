from datetime import date

import pandas as pd

from backtest.core.contracts import BarRequest
from backtest.data.akshare_provider import AkShareProvider


def test_akshare_provider_normalizes_daily_columns(monkeypatch):
    calls = {}

    def fake_stock_zh_a_hist(symbol, period, start_date, end_date, adjust):
        calls.update(
            {
                "symbol": symbol,
                "period": period,
                "start_date": start_date,
                "end_date": end_date,
                "adjust": adjust,
            }
        )
        return pd.DataFrame(
            {
                "日期": ["2025-01-02"],
                "股票代码": ["000001"],
                "开盘": [10.0],
                "收盘": [10.5],
                "最高": [11.0],
                "最低": [9.8],
                "成交量": [1000],
                "成交额": [10500.0],
            }
        )

    import backtest.data.akshare_provider as module

    monkeypatch.setattr(module.ak, "stock_zh_a_hist", fake_stock_zh_a_hist)

    provider = AkShareProvider()
    result = provider.fetch_bars(
        BarRequest(
            symbols=["000001.SZ"],
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 2),
        )
    )

    assert calls == {
        "symbol": "000001",
        "period": "daily",
        "start_date": "20250102",
        "end_date": "20250102",
        "adjust": "qfq",
    }
    assert result.loc[0, "symbol"] == "000001.SZ"
    assert result.loc[0, "frequency"] == "1d"
    assert result.loc[0, "adjust"] == "qfq"
