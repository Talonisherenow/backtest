import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from backtest.broker.execution import BrokerResult
from backtest.reports.html import render_html_report


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )


class FileReportWriter:
    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)

    def write(
        self,
        run_id: str,
        broker_result: BrokerResult,
        metrics: dict[str, Any],
        manifest: dict[str, Any],
    ) -> Path:
        run_dir = self.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        _write_json(run_dir / "manifest.json", manifest)
        _write_json(run_dir / "metrics.json", metrics)

        broker_result.equity_curve.to_parquet(run_dir / "equity_curve.parquet", index=False)
        broker_result.positions.to_parquet(run_dir / "positions.parquet", index=False)
        broker_result.orders.to_parquet(run_dir / "orders.parquet", index=False)
        broker_result.trades.to_parquet(run_dir / "trades.parquet", index=False)

        html = render_html_report(
            title=f"Backtest Report - {run_id}",
            metrics=metrics,
            manifest=manifest,
        )
        (run_dir / "report.html").write_text(html, encoding="utf-8")

        return run_dir
