import akshare as ak
import pandas as pd

from backtest.core.contracts import BarRequest
from backtest.core.enums import AdjustMode, Frequency
from backtest.core.frames import BAR_COLUMNS, validate_bar_frame
from backtest.core.symbols import akshare_symbol, normalize_symbol


class AkShareProvider:
    def fetch_bars(self, request: BarRequest) -> pd.DataFrame:
        if request.frequency != Frequency.DAILY:
            raise ValueError("AkShareProvider MVP supports only daily bars")

        frames: list[pd.DataFrame] = []
        for symbol in request.symbols:
            normalized_symbol = normalize_symbol(symbol)
            raw = ak.stock_zh_a_hist(
                symbol=akshare_symbol(normalized_symbol),
                period="daily",
                start_date=request.start_date.strftime("%Y%m%d"),
                end_date=request.end_date.strftime("%Y%m%d"),
                adjust="" if request.adjust == AdjustMode.NONE else request.adjust.value,
            )
            if raw.empty:
                continue

            frame = raw.rename(
                columns={
                    "日期": "date",
                    "股票代码": "symbol",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "volume",
                    "成交额": "amount",
                }
            )
            frame["symbol"] = normalized_symbol
            frame["frequency"] = request.frequency.value
            frame["adjust"] = request.adjust.value
            frames.append(frame[BAR_COLUMNS])

        if not frames:
            return pd.DataFrame(columns=BAR_COLUMNS)

        return validate_bar_frame(pd.concat(frames, ignore_index=True))
