import importlib.util
from pathlib import Path

import pandas as pd

from backtest.core.frames import validate_signal_frame
from backtest.core.targets import validate_target_portfolio_frame
from backtest.signals.context import StrategyContext


def legacy_signals_to_target_portfolio(
    signals: pd.DataFrame,
    universe: list[str] | None = None,
) -> pd.DataFrame:
    frame = signals.rename(
        columns={
            "date": "timestamp",
            "symbol": "instrument_id",
        }
    )
    return validate_target_portfolio_frame(frame, universe=universe)


class FileSignalProvider:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self, stock_pool: list[str]) -> pd.DataFrame:
        if self.path.suffix.lower() == ".csv":
            frame = pd.read_csv(self.path, dtype={"symbol": str})
        elif self.path.suffix.lower() == ".parquet":
            frame = pd.read_parquet(self.path)
        else:
            raise ValueError(f"Unsupported signal file type: {self.path.suffix}")
        return validate_signal_frame(frame, stock_pool=stock_pool)


class PythonSignalProvider:
    def __init__(self, path: str | Path, function_name: str = "generate_signals") -> None:
        self.path = Path(path)
        self.function_name = function_name

    def load(self, context: StrategyContext) -> pd.DataFrame:
        spec = importlib.util.spec_from_file_location("user_strategy", self.path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Cannot load strategy module: {self.path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, self.function_name)
        frame = fn(context)
        return validate_signal_frame(frame, stock_pool=context.stock_pool)
