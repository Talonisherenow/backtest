from datetime import date
from pathlib import Path

import pytest

from backtest.config.loader import load_config


def test_load_config_normalizes_stock_pool(tmp_path: Path):
    config_path = tmp_path / "demo.yaml"
    config_path.write_text(
        """
project:
  name: demo
data:
  source: akshare
  frequency: 1d
  adjust: qfq
  start_date: "2025-01-01"
  end_date: "2025-01-31"
  stock_pool:
    symbols:
      - "000001"
signals:
  type: file
  path: signals/demo.csv
execution:
  timing: next_open
  initial_cash: 1000000
  commission_rate: 0.0003
  min_commission: 5
  stamp_tax_rate: 0.0005
  slippage_rate: 0.0005
  board_lot_size: 100
metrics:
  builtin:
    - total_return
report:
  output_dir: runs
  html: true
  charts: true
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.project.name == "demo"
    assert config.data.stock_pool.symbols == ["000001.SZ"]
    assert config.signals.path == tmp_path / "signals/demo.csv"
    assert config.report.output_dir == tmp_path / "runs"


def test_load_config_resolves_relative_custom_metric_paths(tmp_path: Path):
    config_path = tmp_path / "demo.yaml"
    config_path.write_text(
        """
project:
  name: demo
data:
  source: akshare
  frequency: 1d
  adjust: qfq
  start_date: "2025-01-01"
  end_date: "2025-01-31"
  stock_pool:
    symbols:
      - "000001.SZ"
signals:
  type: file
  path: signals/demo.csv
execution:
  timing: next_open
  initial_cash: 1000000
  commission_rate: 0.0003
  min_commission: 5
  stamp_tax_rate: 0.0005
  slippage_rate: 0.0005
  board_lot_size: 100
metrics:
  builtin:
    - total_return
  custom:
    - path: strategies/metrics.py
      class: MyMetric
report:
  output_dir: runs
  html: true
  charts: true
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.metrics.custom[0]["path"] == str(tmp_path / "strategies/metrics.py")


def test_load_config_accepts_stock_pool_symbols_file(tmp_path: Path):
    symbols_path = tmp_path / "sample_symbols.txt"
    symbols_path.write_text("600000.SH\n000001\n430017\n", encoding="utf-8")
    config_path = tmp_path / "demo.yaml"
    config_path.write_text(
        """
project:
  name: demo
data:
  source: akshare
  frequency: 1d
  adjust: qfq
  start_date: "2025-01-01"
  end_date: "2025-01-31"
  stock_pool:
    symbols_file: sample_symbols.txt
signals:
  type: file
  path: signals/demo.csv
execution:
  timing: next_open
  initial_cash: 1000000
  commission_rate: 0.0003
  min_commission: 5
  stamp_tax_rate: 0.0005
  slippage_rate: 0.0005
  board_lot_size: 100
metrics:
  builtin:
    - total_return
report:
  output_dir: runs
  html: true
  charts: true
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.data.stock_pool.symbols == ["600000.SH", "000001.SZ", "430017.BJ"]
    assert config.data.stock_pool.symbols_file == symbols_path


def test_load_config_rejects_end_before_start(tmp_path: Path):
    config_path = tmp_path / "bad.yaml"
    config_path.write_text(
        """
project:
  name: bad
data:
  source: akshare
  frequency: 1d
  adjust: qfq
  start_date: "2025-02-01"
  end_date: "2025-01-31"
  stock_pool:
    symbols:
      - "000001.SZ"
signals:
  type: file
  path: signals/demo.csv
execution:
  timing: next_open
  initial_cash: 1000000
  commission_rate: 0.0003
  min_commission: 5
  stamp_tax_rate: 0.0005
  slippage_rate: 0.0005
  board_lot_size: 100
metrics:
  builtin:
    - total_return
report:
  output_dir: runs
  html: true
  charts: true
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="end_date must be on or after start_date"):
        load_config(config_path)
