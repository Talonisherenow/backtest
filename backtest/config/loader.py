from pathlib import Path
from typing import Any

import yaml

from backtest.config.models import BacktestConfig


def _resolve_relative_path(base_dir: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return base_dir / path


def load_config(path: str | Path) -> BacktestConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle)
    config = BacktestConfig.model_validate(data)
    base_dir = config_path.parent

    config.signals.path = _resolve_relative_path(base_dir, config.signals.path)
    config.report.output_dir = _resolve_relative_path(base_dir, config.report.output_dir)
    for custom_metric in config.metrics.custom:
        if "path" in custom_metric:
            custom_metric["path"] = str(_resolve_relative_path(base_dir, Path(custom_metric["path"])))

    return config
