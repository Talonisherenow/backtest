from datetime import date
from pathlib import Path

import pandas as pd

from backtest.signals.context import StrategyContext
from backtest.signals.providers import FileSignalProvider, PythonSignalProvider


def test_file_signal_provider_reads_csv_and_validates(tmp_path: Path):
    path = tmp_path / "signals.csv"
    path.write_text(
        "date,symbol,target_weight\n2025-01-02,000001,0.25\n",
        encoding="utf-8",
    )

    provider = FileSignalProvider(path)
    result = provider.load(stock_pool=["000001.SZ"])

    assert result.loc[0, "symbol"] == "000001.SZ"
    assert result.loc[0, "target_weight"] == 0.25


def test_python_signal_provider_calls_function(tmp_path: Path):
    strategy_path = tmp_path / "strategy.py"
    strategy_path.write_text(
        """
import pandas as pd

def generate_signals(context):
    assert context.stock_pool == ["000001.SZ"]
    return pd.DataFrame({"date": ["2025-01-02"], "symbol": ["000001.SZ"], "target_weight": [0.20]})
""",
        encoding="utf-8",
    )
    context = StrategyContext(
        bars=pd.DataFrame(),
        stock_pool=["000001.SZ"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        params={},
    )

    provider = PythonSignalProvider(strategy_path, function_name="generate_signals")
    result = provider.load(context=context)

    assert result.loc[0, "target_weight"] == 0.20
