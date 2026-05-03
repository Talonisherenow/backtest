import json
from pathlib import Path

import pandas as pd

from backtest.config.loader import load_config
from backtest.engine import BacktestEngine


def _write_config(tmp_path: Path, project_name: str = "Task 11 Demo") -> Path:
    signals_path = tmp_path / "signals.csv"
    output_dir = tmp_path / "runs"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        f"""
project:
  name: "{project_name}"
data:
  source: fixture
  frequency: 1d
  adjust: qfq
  start_date: 2025-01-02
  end_date: 2025-01-06
  stock_pool:
    symbols:
      - 000001.SZ
signals:
  type: file
  path: "{signals_path}"
execution:
  timing: next_open
  initial_cash: 100000
  commission_rate: 0.0003
  min_commission: 5
  stamp_tax_rate: 0.0005
  transfer_fee_rate: 0.00001
  slippage_rate: 0.0
  board_lot_size: 100
metrics:
  builtin:
    - total_return
    - max_drawdown
report:
  output_dir: "{output_dir}"
  html: true
  charts: false
""",
        encoding="utf-8",
    )
    signals_path.write_text(
        "date,symbol,target_weight\n2025-01-02,000001.SZ,0.20\n",
        encoding="utf-8",
    )
    return config_path


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06"]),
            "symbol": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "open": [10.0, 10.0, 12.0],
            "high": [10.5, 10.5, 12.5],
            "low": [9.5, 9.5, 11.5],
            "close": [10.0, 10.0, 12.0],
            "volume": [10000, 10000, 10000],
            "amount": [100000, 100000, 120000],
            "frequency": ["1d", "1d", "1d"],
            "adjust": ["qfq", "qfq", "qfq"],
        }
    )


def test_backtest_engine_runs_with_bar_override_and_writes_reports(tmp_path: Path):
    config_path = _write_config(tmp_path)
    config = load_config(config_path)

    run_dir = BacktestEngine(config, config_path=config_path, bars_override=_bars()).run()

    assert (run_dir / "report.html").exists()
    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "orders.parquet").exists()
    assert "/" not in run_dir.name

    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert "total_return" in metrics
    assert "max_drawdown" in metrics

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["config_hash"]
    assert manifest["project_name"] == "Task 11 Demo"
    assert manifest["signal_source"] == "file"
    assert manifest["data_source"] == "fixture"
    assert manifest["symbols"] == ["000001.SZ"]
    assert manifest["start_date"] == "2025-01-02"
    assert manifest["end_date"] == "2025-01-06"


def test_backtest_engine_slugifies_project_name_in_run_id(tmp_path: Path):
    config_path = _write_config(tmp_path, project_name="Task 11/Demo Run")
    config = load_config(config_path)

    run_dir = BacktestEngine(config, config_path=config_path, bars_override=_bars()).run()

    assert run_dir.parent == config.report.output_dir
    assert run_dir.name.startswith("Task_11_Demo_Run_")
    assert "/" not in run_dir.name
