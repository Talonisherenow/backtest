import inspect
from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from backtest.cli.app import app
from backtest.core.enums import AdjustMode, Frequency
from backtest.data.metadata import MetadataStore
from backtest.data.tasks import CrawlTaskManager


def _write_config(tmp_path: Path) -> Path:
    signals_path = tmp_path / "signals.csv"
    signals_path.write_text(
        "date,symbol,target_weight\n2025-01-02,000001.SZ,0.5\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
project:
  name: cli-demo
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
  path: signals.csv
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
    return config_path


def test_validate_config_cli_accepts_valid_config(tmp_path: Path):
    config_path = _write_config(tmp_path)

    result = CliRunner().invoke(app, ["validate", "config", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Config is valid" in result.output


def test_validate_signals_cli_accepts_path_option(tmp_path: Path):
    signals_path = tmp_path / "signals.csv"
    signals_path.write_text(
        "date,symbol,target_weight\n"
        "2025-01-02,000001.SZ,0.1\n"
        "2025-01-02,600519.SH,0.2\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "validate",
            "signals",
            "--path",
            str(signals_path),
            "--symbol",
            "000001.SZ",
            "--symbol",
            "600519.SH",
        ],
    )

    assert result.exit_code == 0
    assert "Signals are valid" in result.output


def test_data_sync_cli_accepts_bars_root_option_for_non_akshare_config(tmp_path: Path):
    config_path = _write_config(tmp_path)
    config_path.write_text(config_path.read_text(encoding="utf-8").replace("source: akshare", "source: fixture"))

    result = CliRunner().invoke(
        app,
        [
            "data",
            "sync",
            "--config",
            str(config_path),
            "--metadata",
            str(tmp_path / "metadata.sqlite"),
            "--bars-root",
            str(tmp_path / "bars"),
        ],
    )

    assert result.exit_code == 1
    assert "Only source=akshare is supported" in result.output


def test_data_inventory_cli_handles_empty_metadata(tmp_path: Path):
    metadata_path = tmp_path / "metadata.sqlite"

    result = CliRunner().invoke(app, ["data", "inventory", "--metadata", str(metadata_path)])

    assert result.exit_code == 0
    assert "No cached data" in result.output


def test_data_coverage_cli_prints_missing_ranges(tmp_path: Path):
    config_path = _write_config(tmp_path)
    metadata_path = tmp_path / "metadata.sqlite"

    result = CliRunner().invoke(
        app,
        ["data", "coverage", "--config", str(config_path), "--metadata", str(metadata_path)],
    )

    assert result.exit_code == 0
    assert "000001.SZ missing 2025-01-01 to 2025-01-31" in result.output


def test_data_retry_cli_marks_failed_tasks_retrying(tmp_path: Path):
    metadata_path = tmp_path / "metadata.sqlite"
    metadata = MetadataStore(metadata_path)
    tasks = CrawlTaskManager(metadata)
    task_id = tasks.create_task(
        "000001.SZ",
        Frequency.DAILY,
        AdjustMode.QFQ,
        date(2025, 1, 1),
        date(2025, 1, 31),
        "akshare",
    )
    tasks.mark_running(task_id)
    tasks.mark_failed(task_id, "network timeout")

    result = CliRunner().invoke(
        app,
        ["data", "retry", "--failed", "--metadata", str(metadata_path)],
    )

    assert result.exit_code == 0
    assert f"Queued retry for task {task_id}" in result.output
    assert CrawlTaskManager(MetadataStore(metadata_path)).list_tasks()[0].status == "retrying"


def test_crawl_task_manager_mark_retrying_accepts_integer_task_id():
    signature = inspect.signature(CrawlTaskManager.mark_retrying)

    assert signature.parameters["task_id"].annotation is int
