import inspect
from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from backtest.cli import data as data_cli
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


def test_validate_signals_cli_reports_malformed_signal_files(tmp_path: Path):
    signals_path = tmp_path / "signals.csv"
    signals_path.write_text("date,target_weight\n2025-01-02,0.1\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["validate", "signals", "--path", str(signals_path)])

    assert result.exit_code == 1
    assert "symbol" in result.output


def test_data_sync_cli_passes_bars_root_to_store(tmp_path: Path, monkeypatch):
    config_path = _write_config(tmp_path)
    bars_root = tmp_path / "custom-bars"
    captured = {}

    class NoopSyncService:
        def __init__(self, provider, store, catalog, tasks) -> None:
            captured["provider"] = provider
            captured["store_root"] = store.root

        def sync(self, **kwargs) -> None:
            captured["sync_kwargs"] = kwargs

    provider = object()
    monkeypatch.setattr(data_cli, "AkShareProvider", lambda: provider)
    monkeypatch.setattr(data_cli, "DataSyncService", NoopSyncService)

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
            str(bars_root),
        ],
    )

    assert result.exit_code == 0
    assert "Data sync complete" in result.output
    assert captured["provider"] is provider
    assert captured["store_root"] == bars_root
    assert captured["sync_kwargs"]["symbols"] == ["000001.SZ"]


def test_data_sync_cli_reports_sync_errors(tmp_path: Path, monkeypatch):
    config_path = _write_config(tmp_path)

    class FailingSyncService:
        def __init__(self, provider, store, catalog, tasks) -> None:
            pass

        def sync(self, **kwargs) -> None:
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(data_cli, "AkShareProvider", lambda: object())
    monkeypatch.setattr(data_cli, "DataSyncService", FailingSyncService)

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
    assert "provider unavailable" in result.output


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
    record = CrawlTaskManager(MetadataStore(metadata_path)).list_tasks()[0]
    assert record.status == "retrying"
    assert record.attempts == 1
    assert record.last_error is None


def test_data_universe_cli_writes_provider_output(tmp_path: Path, monkeypatch):
    output_path = tmp_path / "a_share_all.csv"

    class FakeUniverseProvider:
        def fetch_a_share_universe(self):
            import pandas as pd

            return pd.DataFrame(
                {
                    "symbol": ["600000.SH", "000001.SZ"],
                    "code": ["600000", "000001"],
                    "name": ["浦发银行", "平安银行"],
                    "exchange": ["SH", "SZ"],
                    "board": ["主板", "主板"],
                    "list_date": ["1999-11-10", "1991-04-03"],
                    "industry": ["", "J 金融业"],
                }
            )

    monkeypatch.setattr(data_cli, "AkShareUniverseProvider", FakeUniverseProvider)

    result = CliRunner().invoke(app, ["data", "universe", "--output", str(output_path)])

    assert result.exit_code == 0
    assert "Wrote 2 symbols" in result.output
    assert "600000.SH" in output_path.read_text(encoding="utf-8")


def test_data_sample_pool_cli_writes_seeded_random_symbols(tmp_path: Path):
    universe_path = tmp_path / "universe.csv"
    output_path = tmp_path / "sample.txt"
    universe_path.write_text(
        "symbol,code,name,exchange,board,list_date,industry\n"
        "600000.SH,600000,浦发银行,SH,主板,1999-11-10,\n"
        "000001.SZ,000001,平安银行,SZ,主板,1991-04-03,J 金融业\n"
        "430017.BJ,430017,星昊医药,BJ,北交所,2023-06-20,医药制造业\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "data",
            "sample-pool",
            "--universe",
            str(universe_path),
            "--size",
            "2",
            "--seed",
            "7",
            "--output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    assert "Wrote 2 sampled symbols" in result.output
    symbols = output_path.read_text(encoding="utf-8").splitlines()
    assert len(symbols) == 2
    assert set(symbols).issubset({"600000.SH", "000001.SZ", "430017.BJ"})


def test_crawl_task_manager_mark_retrying_accepts_integer_task_id():
    signature = inspect.signature(CrawlTaskManager.mark_retrying)

    assert signature.parameters["task_id"].annotation is int
