import json
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from backtest.cli.app import app
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


def test_backtest_engine_python_signal_context_dates_are_iso_strings(tmp_path: Path):
    signals_path = tmp_path / "strategy.py"
    output_dir = tmp_path / "runs"
    config_path = tmp_path / "config.yaml"
    signal_output_path = tmp_path / "context_dates.txt"
    signals_path.write_text(
        f"""
from pathlib import Path

import pandas as pd


def generate_signals(context):
    assert isinstance(context.start_date, str)
    assert isinstance(context.end_date, str)
    assert context.start_date == "2025-01-02"
    assert context.end_date == "2025-01-06"
    Path({str(signal_output_path)!r}).write_text(f"{{context.start_date}},{{context.end_date}}", encoding="utf-8")
    return pd.DataFrame({{"date": ["2025-01-02"], "symbol": ["000001.SZ"], "target_weight": [0.20]}})
""",
        encoding="utf-8",
    )
    config_path.write_text(
        f"""
project:
  name: python-context
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
  type: python
  path: "{signals_path}"
  function: generate_signals
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
report:
  output_dir: "{output_dir}"
  html: true
  charts: false
""",
        encoding="utf-8",
    )

    config = load_config(config_path)
    BacktestEngine(config, config_path=config_path, bars_override=_bars()).run()

    assert signal_output_path.read_text(encoding="utf-8") == "2025-01-02,2025-01-06"


def test_backtest_engine_writes_custom_metrics(tmp_path: Path):
    metric_path = tmp_path / "custom_metric.py"
    config_path = _write_config(tmp_path)
    original_config = config_path.read_text(encoding="utf-8")
    config_path.write_text(
        original_config.replace(
            "metrics:\n  builtin:\n    - total_return\n    - max_drawdown\n",
            "metrics:\n  builtin:\n    - total_return\n  custom:\n    - path: custom_metric.py\n      class: MyMetric\n",
        ),
        encoding="utf-8",
    )
    metric_path.write_text(
        """
from backtest.core.contracts import MetricResult
from backtest.core.enums import MetricResultKind


class MyMetric:
    name = "custom_score"

    def calculate(self, context):
        return MetricResult(name=self.name, kind=MetricResultKind.SCALAR, value=123)
""",
        encoding="utf-8",
    )
    config = load_config(config_path)

    run_dir = BacktestEngine(config, config_path=config_path, bars_override=_bars()).run()

    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["custom_score"]["value"] == 123


def test_backtest_engine_rejects_empty_bars(tmp_path: Path):
    config_path = _write_config(tmp_path)
    config = load_config(config_path)
    empty_bars = pd.DataFrame(columns=_bars().columns)

    with pytest.raises(ValueError, match="No bar data"):
        BacktestEngine(config, config_path=config_path, bars_override=empty_bars).run()


def test_run_cli_accepts_config_option_without_parse_error(tmp_path: Path):
    config_path = _write_config(tmp_path)

    result = CliRunner().invoke(app, ["run", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "cached bar loading" in result.output
