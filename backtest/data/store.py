from datetime import date
from pathlib import Path

import pandas as pd

from backtest.core.enums import AdjustMode, Frequency
from backtest.core.frames import BAR_COLUMNS, validate_bar_frame
from backtest.core.symbols import normalize_symbol, safe_symbol_path


class ParquetBarStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def partition_path(
        self, symbol: str, frequency: Frequency, adjust: AdjustMode, year: int
    ) -> Path:
        return (
            self.root
            / f"frequency={frequency.value}"
            / f"adjust={adjust.value}"
            / f"symbol={safe_symbol_path(symbol)}"
            / f"year={year}"
            / "bars.parquet"
        )

    def write_bars(self, bars: pd.DataFrame) -> list[Path]:
        validated = validate_bar_frame(bars)
        written: list[Path] = []
        for (symbol, frequency, adjust, year), group in validated.groupby(
            ["symbol", "frequency", "adjust", validated["date"].dt.year]
        ):
            path = self.partition_path(
                symbol, Frequency(frequency), AdjustMode(adjust), int(year)
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                existing = pd.read_parquet(path)
                group = pd.concat([existing, group], ignore_index=True)
            group = group.drop_duplicates(["date", "symbol"], keep="last")
            group = group.sort_values(["symbol", "date"]).reset_index(drop=True)
            tmp_path = path.with_suffix(".tmp.parquet")
            group.to_parquet(tmp_path, index=False)
            tmp_path.replace(path)
            written.append(path)
        return written

    def read_bars(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        frequency: Frequency,
        adjust: AdjustMode,
    ) -> pd.DataFrame:
        normalized_symbols = [normalize_symbol(symbol) for symbol in symbols]
        frames: list[pd.DataFrame] = []
        for symbol in normalized_symbols:
            for year in range(start_date.year, end_date.year + 1):
                path = self.partition_path(symbol, frequency, adjust, year)
                if path.exists():
                    frames.append(pd.read_parquet(path))
        if not frames:
            return pd.DataFrame(columns=BAR_COLUMNS)
        result = pd.concat(frames, ignore_index=True)
        result["date"] = pd.to_datetime(result["date"])
        end_exclusive = pd.Timestamp(end_date) + pd.Timedelta(days=1)
        mask = (
            result["symbol"].isin(normalized_symbols)
            & (result["date"] >= pd.Timestamp(start_date))
            & (result["date"] < end_exclusive)
        )
        return result.loc[mask].sort_values(["symbol", "date"]).reset_index(drop=True)
