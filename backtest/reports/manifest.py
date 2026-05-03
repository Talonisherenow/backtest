from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from backtest import __version__


def _json_friendly(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def build_manifest(
    *,
    run_id: str,
    project_name: str,
    config_path: str | Path,
    config_hash: str,
    signal_source: str,
    data_source: str,
    symbols: list[str],
    start_date: date | str,
    end_date: date | str,
    benchmark: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "project_name": project_name,
        "created_at": datetime.now(UTC).isoformat(),
        "config_path": _json_friendly(config_path),
        "config_hash": config_hash,
        "signal_source": signal_source,
        "data_source": data_source,
        "symbols": symbols,
        "start_date": _json_friendly(start_date),
        "end_date": _json_friendly(end_date),
        "benchmark": benchmark,
        "engine_version": __version__,
    }
