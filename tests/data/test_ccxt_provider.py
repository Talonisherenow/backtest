import sys
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from backtest.core.contracts import BarRequest
from backtest.core.enums import AdjustMode, Frequency
from backtest.data.ccxt_provider import CCXTOHLCVProvider


def _ms(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=UTC).timestamp() * 1000)


class FakeExchange:
    def __init__(
        self,
        batches: list[list[list[float]]] | None = None,
        *,
        has_ohlcv: bool = True,
        timeframes: dict[str, str] | None = None,
        markets: dict[str, dict] | None = None,
    ) -> None:
        self.has = {"fetchOHLCV": has_ohlcv}
        self.timeframes = timeframes or {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
            "4h": "4h",
            "1d": "1d",
        }
        self.markets = markets or {"BTC/USDT": {}}
        self.batches = list(batches or [])
        self.calls: list[dict] = []
        self.loaded = False

    def load_markets(self):
        self.loaded = True
        return self.markets

    def fetch_ohlcv(self, symbol, timeframe="1m", since=None, limit=None, params=None):
        self.calls.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "since": since,
                "limit": limit,
                "params": params,
            }
        )
        if not self.batches:
            return []
        return self.batches.pop(0)


def test_ccxt_provider_fetches_ohlcv_as_bar_frame():
    exchange = FakeExchange(
        batches=[
            [
                [_ms("2025-01-01T00:00:00"), 100.0, 110.0, 90.0, 105.0, 2.0],
                [_ms("2025-01-01T04:00:00"), 105.0, 115.0, 95.0, 110.0, 3.0],
            ],
            [],
        ]
    )
    provider = CCXTOHLCVProvider(exchange=exchange, limit=2, now_ms=lambda: _ms("2025-01-02T00:00:00"))

    result = provider.fetch_bars(
        BarRequest(
            symbols=["btc/usdt"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            frequency=Frequency.HOUR_4,
            adjust=AdjustMode.NONE,
            source="ccxt:binance",
        )
    )

    assert exchange.loaded is True
    assert result["symbol"].tolist() == ["BTC/USDT", "BTC/USDT"]
    assert result["frequency"].tolist() == ["4h", "4h"]
    assert result["adjust"].tolist() == ["none", "none"]
    assert result["amount"].tolist() == [210.0, 330.0]
    assert exchange.calls[0]["timeframe"] == "4h"
    assert exchange.calls[0]["limit"] == 2


def test_ccxt_provider_maps_internal_one_hour_to_ccxt_one_hour():
    exchange = FakeExchange(batches=[[]])
    provider = CCXTOHLCVProvider(exchange=exchange, now_ms=lambda: _ms("2025-01-02T00:00:00"))

    provider.fetch_bars(
        BarRequest(
            symbols=["BTC/USDT"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            frequency=Frequency.HOUR_1,
            adjust=AdjustMode.NONE,
            source="ccxt:binance",
        )
    )

    assert exchange.calls[0]["timeframe"] == "1h"


def test_frequency_keeps_legacy_sixty_minute_alias():
    assert Frequency("60m") is Frequency.HOUR_1
    assert Frequency("60m").value == "1h"


def test_ccxt_provider_caps_bitget_historical_ohlcv_limit_to_200():
    exchange = FakeExchange(batches=[[]])
    provider = CCXTOHLCVProvider(
        exchange_id="bitget",
        exchange=exchange,
        limit=1000,
        now_ms=lambda: _ms("2025-01-02T00:00:00"),
    )

    provider.fetch_bars(
        BarRequest(
            symbols=["BTC/USDT"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            frequency=Frequency.MIN_1,
            adjust=AdjustMode.NONE,
            source="ccxt:bitget",
        )
    )

    assert exchange.calls[0]["limit"] == 200


def test_ccxt_provider_keeps_configured_limit_for_non_bitget_exchanges():
    exchange = FakeExchange(batches=[[]])
    provider = CCXTOHLCVProvider(
        exchange_id="binance",
        exchange=exchange,
        limit=1000,
        now_ms=lambda: _ms("2025-01-02T00:00:00"),
    )

    provider.fetch_bars(
        BarRequest(
            symbols=["BTC/USDT"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            frequency=Frequency.MIN_1,
            adjust=AdjustMode.NONE,
            source="ccxt:binance",
        )
    )

    assert exchange.calls[0]["limit"] == 1000


def test_ccxt_provider_passes_env_proxy_to_ccxt_exchange(monkeypatch):
    captured_config: dict = {}

    class FakeExchangeFactory:
        def __init__(self, config):
            captured_config.update(config)

    monkeypatch.setenv("CCXT_HTTP_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("CCXT_HTTPS_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setitem(sys.modules, "ccxt", SimpleNamespace(bitget=FakeExchangeFactory))

    CCXTOHLCVProvider(exchange_id="bitget")._exchange()

    assert captured_config["enableRateLimit"] is True
    assert captured_config["proxies"] == {
        "http": "http://127.0.0.1:7897",
        "https": "http://127.0.0.1:7897",
    }


def test_ccxt_provider_paginates_from_last_candle_timestamp():
    first_timestamp = _ms("2025-01-01T00:00:00")
    second_timestamp = _ms("2025-01-01T04:00:00")
    third_timestamp = _ms("2025-01-01T08:00:00")
    exchange = FakeExchange(
        batches=[
            [
                [first_timestamp, 100.0, 110.0, 90.0, 105.0, 2.0],
                [second_timestamp, 105.0, 115.0, 95.0, 110.0, 3.0],
            ],
            [[third_timestamp, 110.0, 120.0, 100.0, 115.0, 4.0]],
            [],
        ]
    )
    provider = CCXTOHLCVProvider(exchange=exchange, limit=2, now_ms=lambda: _ms("2025-01-02T00:00:00"))

    result = provider.fetch_bars(
        BarRequest(
            symbols=["BTC/USDT"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            frequency=Frequency.HOUR_4,
            adjust=AdjustMode.NONE,
            source="ccxt:binance",
        )
    )

    assert len(result) == 3
    assert exchange.calls[1]["since"] == third_timestamp


def test_ccxt_provider_reuses_last_timestamp_for_bitget_daily_pagination():
    first_timestamp = _ms("2025-01-01T00:00:00")
    second_timestamp = _ms("2025-01-02T00:00:00")
    third_timestamp = _ms("2025-01-03T00:00:00")
    exchange = FakeExchange(
        batches=[
            [
                [first_timestamp, 100.0, 110.0, 90.0, 105.0, 2.0],
                [second_timestamp, 105.0, 115.0, 95.0, 110.0, 3.0],
            ],
            [[third_timestamp, 110.0, 120.0, 100.0, 115.0, 4.0]],
            [],
        ]
    )
    provider = CCXTOHLCVProvider(
        exchange_id="bitget",
        exchange=exchange,
        limit=2,
        now_ms=lambda: _ms("2025-01-04T00:00:00"),
    )

    provider.fetch_bars(
        BarRequest(
            symbols=["BTC/USDT"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 3),
            frequency=Frequency.DAILY,
            adjust=AdjustMode.NONE,
            source="ccxt:bitget",
        )
    )

    assert exchange.calls[1]["since"] == second_timestamp


def test_ccxt_provider_offsets_initial_since_for_bitget_daily_pagination():
    first_timestamp = _ms("2025-01-01T00:00:00")
    second_timestamp = _ms("2025-01-02T00:00:00")
    exchange = FakeExchange(
        batches=[
            [
                [first_timestamp, 100.0, 110.0, 90.0, 105.0, 2.0],
                [second_timestamp, 105.0, 115.0, 95.0, 110.0, 3.0],
            ],
            [],
        ]
    )
    provider = CCXTOHLCVProvider(
        exchange_id="bitget",
        exchange=exchange,
        now_ms=lambda: _ms("2025-01-02T00:00:00"),
    )

    provider.fetch_bars(
        BarRequest(
            symbols=["BTC/USDT"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 2),
            frequency=Frequency.DAILY,
            adjust=AdjustMode.NONE,
            source="ccxt:bitget",
        )
    )

    assert exchange.calls[0]["since"] == first_timestamp - 24 * 60 * 60 * 1000


def test_ccxt_provider_stops_when_bitget_daily_repeats_current_incomplete_candle():
    first_timestamp = _ms("2025-01-01T00:00:00")
    second_timestamp = _ms("2025-01-02T00:00:00")
    incomplete_timestamp = _ms("2025-01-03T00:00:00")
    exchange = FakeExchange(
        batches=[
            [
                [first_timestamp, 100.0, 110.0, 90.0, 105.0, 2.0],
                [second_timestamp, 105.0, 115.0, 95.0, 110.0, 3.0],
                [incomplete_timestamp, 110.0, 120.0, 100.0, 115.0, 4.0],
            ],
            [[incomplete_timestamp, 110.0, 120.0, 100.0, 115.0, 4.0]],
        ]
    )
    provider = CCXTOHLCVProvider(
        exchange_id="bitget",
        exchange=exchange,
        limit=3,
        now_ms=lambda: _ms("2025-01-03T12:00:00"),
    )

    result = provider.fetch_bars(
        BarRequest(
            symbols=["BTC/USDT"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 3),
            frequency=Frequency.DAILY,
            adjust=AdjustMode.NONE,
            source="ccxt:bitget",
        )
    )

    assert result["date"].dt.strftime("%Y-%m-%d").tolist() == ["2025-01-01", "2025-01-02"]


def test_ccxt_provider_waits_between_paginated_requests():
    first_timestamp = _ms("2025-01-01T00:00:00")
    second_timestamp = _ms("2025-01-01T00:01:00")
    sleep_calls: list[float] = []
    exchange = FakeExchange(
        batches=[
            [[first_timestamp, 100.0, 110.0, 90.0, 105.0, 2.0]],
            [[second_timestamp, 105.0, 115.0, 95.0, 110.0, 3.0]],
            [],
        ]
    )
    provider = CCXTOHLCVProvider(
        exchange=exchange,
        limit=1,
        page_delay_seconds=0.25,
        sleep=sleep_calls.append,
        now_ms=lambda: _ms("2025-01-02T00:00:00"),
    )

    provider.fetch_bars(
        BarRequest(
            symbols=["BTC/USDT"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            frequency=Frequency.MIN_1,
            adjust=AdjustMode.NONE,
            source="ccxt:binance",
        )
    )

    assert sleep_calls == [0.25, 0.25]


def test_ccxt_provider_drops_current_incomplete_candle():
    exchange = FakeExchange(
        batches=[
            [
                [_ms("2025-01-01T16:00:00"), 100.0, 110.0, 90.0, 105.0, 2.0],
                [_ms("2025-01-01T20:00:00"), 105.0, 115.0, 95.0, 110.0, 3.0],
            ],
            [],
        ]
    )
    provider = CCXTOHLCVProvider(exchange=exchange, limit=2, now_ms=lambda: _ms("2025-01-01T22:00:00"))

    result = provider.fetch_bars(
        BarRequest(
            symbols=["BTC/USDT"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            frequency=Frequency.HOUR_4,
            adjust=AdjustMode.NONE,
            source="ccxt:binance",
        )
    )

    assert result["date"].dt.hour.tolist() == [16]


def test_ccxt_provider_rejects_adjusted_crypto_bars():
    provider = CCXTOHLCVProvider(exchange=FakeExchange())

    with pytest.raises(ValueError, match="adjust=none"):
        provider.fetch_bars(
            BarRequest(
                symbols=["BTC/USDT"],
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 1),
                frequency=Frequency.HOUR_4,
                adjust=AdjustMode.QFQ,
                source="ccxt:binance",
            )
        )


def test_ccxt_provider_rejects_exchange_without_ohlcv_support():
    provider = CCXTOHLCVProvider(exchange=FakeExchange(has_ohlcv=False))

    with pytest.raises(ValueError, match="does not support fetchOHLCV"):
        provider.fetch_bars(
            BarRequest(
                symbols=["BTC/USDT"],
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 1),
                frequency=Frequency.HOUR_4,
                adjust=AdjustMode.NONE,
                source="ccxt:binance",
            )
        )


def test_ccxt_provider_rejects_missing_symbol():
    provider = CCXTOHLCVProvider(exchange=FakeExchange(markets={"ETH/USDT": {}}))

    with pytest.raises(ValueError, match="not available"):
        provider.fetch_bars(
            BarRequest(
                symbols=["BTC/USDT"],
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 1),
                frequency=Frequency.HOUR_4,
                adjust=AdjustMode.NONE,
                source="ccxt:binance",
            )
        )


def test_ccxt_provider_rejects_unsupported_timeframe():
    provider = CCXTOHLCVProvider(exchange=FakeExchange(timeframes={"1d": "1d"}))

    with pytest.raises(ValueError, match="does not support timeframe"):
        provider.fetch_bars(
            BarRequest(
                symbols=["BTC/USDT"],
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 1),
                frequency=Frequency.HOUR_4,
                adjust=AdjustMode.NONE,
                source="ccxt:binance",
            )
        )
