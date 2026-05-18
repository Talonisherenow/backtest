from datetime import date

import pandas as pd
import requests

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


def test_akshare_provider_falls_back_to_sina_daily_on_network_error(monkeypatch):
    calls = {}

    def fake_stock_zh_a_hist(**kwargs):
        calls["eastmoney"] = kwargs
        raise requests.exceptions.ProxyError("eastmoney proxy closed connection")

    def fake_stock_zh_a_daily(symbol, start_date, end_date, adjust):
        calls["sina"] = {
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "adjust": adjust,
        }
        return pd.DataFrame(
            {
                "date": ["2025-01-02"],
                "open": [10.0],
                "high": [11.0],
                "low": [9.8],
                "close": [10.5],
                "volume": [1000],
                "amount": [10500.0],
            }
        )

    import backtest.data.akshare_provider as module

    monkeypatch.setattr(module.ak, "stock_zh_a_hist", fake_stock_zh_a_hist)
    monkeypatch.setattr(module.ak, "stock_zh_a_daily", fake_stock_zh_a_daily)

    provider = AkShareProvider()
    result = provider.fetch_bars(
        BarRequest(
            symbols=["000858.SZ"],
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 2),
        )
    )

    assert calls["eastmoney"]["symbol"] == "000858"
    assert calls["sina"] == {
        "symbol": "sz000858",
        "start_date": "20250102",
        "end_date": "20250102",
        "adjust": "qfq",
    }
    assert result.loc[0, "symbol"] == "000858.SZ"
    assert result.loc[0, "frequency"] == "1d"
    assert result.loc[0, "adjust"] == "qfq"
