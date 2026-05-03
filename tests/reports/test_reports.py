import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backtest.broker.execution import BrokerResult
from backtest.core.contracts import MetricResult
from backtest.core.enums import MetricResultKind
from backtest.reports.manifest import build_manifest
from backtest.reports.writer import FileReportWriter


def make_broker_result() -> BrokerResult:
    return BrokerResult(
        equity_curve=pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-02"]),
                "equity": [100000.0],
                "cash": [100000.0],
            }
        ),
        positions=pd.DataFrame({"date": [], "symbol": [], "shares": []}),
        orders=pd.DataFrame({"date": [], "symbol": [], "status": []}),
        trades=pd.DataFrame({"date": [], "symbol": [], "side": []}),
    )


def make_manifest() -> dict:
    return build_manifest(
        run_id="demo",
        project_name="demo",
        config_path=Path("configs/demo.yaml"),
        config_hash="abc",
        signal_source="file",
        data_source="fixture",
        symbols=["000001.SZ"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
    )


def test_file_report_writer_outputs_structured_files(tmp_path: Path):
    writer = FileReportWriter(tmp_path)
    run_dir = writer.write(
        run_id="demo",
        broker_result=make_broker_result(),
        metrics={"total_return": 0.0},
        manifest=make_manifest(),
    )

    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "equity_curve.parquet").exists()
    assert (run_dir / "positions.parquet").exists()
    assert (run_dir / "orders.parquet").exists()
    assert (run_dir / "trades.parquet").exists()
    assert (run_dir / "report.html").exists()

    manifest_payload = json.loads((run_dir / "manifest.json").read_text())
    assert manifest_payload["created_at"]
    assert manifest_payload["config_path"] == "configs/demo.yaml"
    assert manifest_payload["start_date"] == "2025-01-01"
    assert manifest_payload["end_date"] == "2025-01-31"

    html = (run_dir / "report.html").read_text()
    assert "total_return" in html
    assert "demo" in html


def test_file_report_writer_serializes_metric_result_with_numpy_scalar(tmp_path: Path):
    metrics = {
        "custom": MetricResult(
            name="custom",
            kind=MetricResultKind.SCALAR,
            value=np.int64(42),
        )
    }

    run_dir = FileReportWriter(tmp_path).write(
        run_id="demo",
        broker_result=make_broker_result(),
        metrics=metrics,
        manifest=make_manifest(),
    )

    payload = json.loads((run_dir / "metrics.json").read_text())
    assert payload["custom"]["value"] == 42


def test_file_report_writer_rejects_run_id_path_traversal(tmp_path: Path):
    with pytest.raises(ValueError, match="run_id"):
        FileReportWriter(tmp_path).write(
            run_id="../escaped",
            broker_result=make_broker_result(),
            metrics={"total_return": 0.0},
            manifest=make_manifest(),
        )
