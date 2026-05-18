import os
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pandas as pd

from backtest.core.contracts import BarRequest
from backtest.core.enums import AdjustMode, Frequency
from backtest.core.frames import BAR_COLUMNS, validate_bar_frame
from backtest.core.symbols import normalize_symbol


CCXT_TIMEFRAME_BY_FREQUENCY = {
    Frequency.MIN_1: "1m",
    Frequency.MIN_5: "5m",
    Frequency.MIN_15: "15m",
    Frequency.MIN_30: "30m",
    Frequency.HOUR_1: "1h",
    Frequency.HOUR_4: "4h",
    Frequency.DAILY: "1d",
}

TIMEFRAME_MS_BY_FREQUENCY = {
    Frequency.MIN_1: 60 * 1000,
    Frequency.MIN_5: 5 * 60 * 1000,
    Frequency.MIN_15: 15 * 60 * 1000,
    Frequency.MIN_30: 30 * 60 * 1000,
    Frequency.HOUR_1: 60 * 60 * 1000,
    Frequency.HOUR_4: 4 * 60 * 60 * 1000,
    Frequency.DAILY: 24 * 60 * 60 * 1000,
}

HISTORICAL_OHLCV_LIMIT_BY_EXCHANGE = {
    "bitget": 200,
}


class CCXTOHLCVProvider:
    def __init__(
        self,
        exchange_id: str = "binance",
        *,
        exchange: Any | None = None,
        limit: int = 1000,
        page_delay_seconds: float = 0.0,
        drop_incomplete: bool = True,
        now_ms: Callable[[], int] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.exchange_id = exchange_id.strip().lower()
        if not self.exchange_id:
            raise ValueError("exchange_id must not be empty")
        self.exchange = exchange
        self.limit = limit
        self.page_delay_seconds = page_delay_seconds
        self.drop_incomplete = drop_incomplete
        self.now_ms = now_ms or self._system_now_ms
        self.sleep = sleep

    def fetch_bars(self, request: BarRequest) -> pd.DataFrame:
        if request.adjust != AdjustMode.NONE:
            raise ValueError("CCXTOHLCVProvider supports only adjust=none")

        frequency = Frequency(request.frequency)
        ccxt_timeframe = CCXT_TIMEFRAME_BY_FREQUENCY[frequency]
        timeframe_ms = TIMEFRAME_MS_BY_FREQUENCY[frequency]
        exchange = self._exchange()
        markets = exchange.load_markets()
        self._validate_exchange(exchange, ccxt_timeframe)

        rows: list[dict[str, object]] = []
        start_ms = self._date_to_ms(request.start_date)
        end_ms = self._date_to_ms(request.end_date + timedelta(days=1))

        for raw_symbol in request.symbols:
            symbol = normalize_symbol(raw_symbol)
            if symbol not in markets:
                raise ValueError(f"{symbol} is not available on CCXT exchange {self.exchange_id}")
            rows.extend(
                self._fetch_symbol_rows(
                    exchange,
                    symbol,
                    frequency,
                    ccxt_timeframe,
                    timeframe_ms,
                    start_ms,
                    end_ms,
                )
            )

        if not rows:
            return pd.DataFrame(columns=BAR_COLUMNS)

        frame = pd.DataFrame(rows, columns=BAR_COLUMNS)
        frame = frame.drop_duplicates(["date", "symbol"], keep="last")
        return validate_bar_frame(frame)

    def _exchange(self):
        if self.exchange is not None:
            return self.exchange

        try:
            import ccxt
        except ImportError as exc:
            raise RuntimeError("ccxt is required for source=ccxt market data") from exc

        exchange_class = getattr(ccxt, self.exchange_id, None)
        if exchange_class is None:
            raise ValueError(f"Unknown CCXT exchange: {self.exchange_id}")
        config: dict[str, Any] = {"enableRateLimit": True}
        proxies = self._proxy_config_from_env()
        if proxies:
            config["proxies"] = proxies
        self.exchange = exchange_class(config)
        return self.exchange

    def _proxy_config_from_env(self) -> dict[str, str]:
        all_proxy = os.environ.get("CCXT_PROXY") or os.environ.get("ALL_PROXY") or os.environ.get("all_proxy")
        http_proxy = (
            os.environ.get("CCXT_HTTP_PROXY")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("http_proxy")
            or all_proxy
        )
        https_proxy = (
            os.environ.get("CCXT_HTTPS_PROXY")
            or os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or all_proxy
        )
        proxies: dict[str, str] = {}
        if http_proxy:
            proxies["http"] = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy
        return proxies

    def _validate_exchange(self, exchange, ccxt_timeframe: str) -> None:
        if not getattr(exchange, "has", {}).get("fetchOHLCV"):
            raise ValueError(f"CCXT exchange {self.exchange_id} does not support fetchOHLCV")

        timeframes = getattr(exchange, "timeframes", None) or {}
        supported = set(timeframes) | set(timeframes.values())
        if supported and ccxt_timeframe not in supported:
            raise ValueError(
                f"CCXT exchange {self.exchange_id} does not support timeframe {ccxt_timeframe}"
            )

    def _fetch_symbol_rows(
        self,
        exchange,
        symbol: str,
        frequency: Frequency,
        ccxt_timeframe: str,
        timeframe_ms: int,
        start_ms: int,
        end_ms: int,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        since = self._initial_since(start_ms, timeframe_ms, frequency)

        while since < end_ms:
            batch = exchange.fetch_ohlcv(
                symbol,
                timeframe=ccxt_timeframe,
                since=since,
                limit=self._effective_limit(),
                params={},
            )
            if not batch:
                break

            batch = sorted(batch, key=lambda item: item[0])
            last_timestamp = int(batch[-1][0])
            for candle in batch:
                if len(candle) < 6 or any(value is None for value in candle[:6]):
                    continue
                timestamp_ms = int(candle[0])
                if timestamp_ms < start_ms or timestamp_ms >= end_ms:
                    continue
                if self.drop_incomplete and timestamp_ms + timeframe_ms > self.now_ms():
                    continue
                rows.append(self._row_from_candle(symbol, frequency, candle))

            next_since = self._next_since(last_timestamp, timeframe_ms, frequency)
            if next_since <= since:
                if self._is_terminal_repeated_candle(last_timestamp, timeframe_ms, end_ms):
                    break
                raise ValueError("CCXT OHLCV pagination did not advance")
            since = next_since
            if self.page_delay_seconds:
                self.sleep(self.page_delay_seconds)

        return rows

    def _effective_limit(self) -> int:
        exchange_limit = HISTORICAL_OHLCV_LIMIT_BY_EXCHANGE.get(self.exchange_id)
        if exchange_limit is None:
            return self.limit
        return min(self.limit, exchange_limit)

    def _next_since(self, last_timestamp: int, timeframe_ms: int, frequency: Frequency) -> int:
        if self.exchange_id == "bitget" and frequency is Frequency.DAILY:
            return last_timestamp
        return last_timestamp + timeframe_ms

    def _initial_since(self, start_ms: int, timeframe_ms: int, frequency: Frequency) -> int:
        if self.exchange_id == "bitget" and frequency is Frequency.DAILY:
            return start_ms - timeframe_ms
        return start_ms

    def _is_terminal_repeated_candle(self, timestamp_ms: int, timeframe_ms: int, end_ms: int) -> bool:
        candle_end_ms = timestamp_ms + timeframe_ms
        if candle_end_ms >= end_ms:
            return True
        return self.drop_incomplete and candle_end_ms > self.now_ms()

    def _row_from_candle(
        self, symbol: str, frequency: Frequency, candle: list[float]
    ) -> dict[str, object]:
        timestamp_ms, open_, high, low, close, volume = candle[:6]
        timestamp = pd.to_datetime(int(timestamp_ms), unit="ms", utc=True).tz_convert(None)
        amount = float(close) * float(volume)
        return {
            "date": timestamp,
            "symbol": symbol,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "amount": amount,
            "frequency": frequency.value,
            "adjust": AdjustMode.NONE.value,
        }

    def _date_to_ms(self, value: date) -> int:
        return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp() * 1000)

    def _system_now_ms(self) -> int:
        return int(datetime.now(UTC).timestamp() * 1000)
