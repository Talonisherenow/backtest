import json
from datetime import date
from pathlib import Path

import pandas as pd

from backtest.broker.execution import BrokerResult
from backtest.reports.manifest import build_manifest
from backtest.reports.writer import FileReportWriter


def test_file_report_writer_outputs_structured_files(tmp_path: Path):
    result = BrokerResult(
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
    manifest = build_manifest(
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

    writer = FileReportWriter(tmp_path)
    run_dir = writer.write(
        run_id="demo",
        broker_result=result,
        metrics={"total_return": 0.0},
        manifest=manifest,
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
