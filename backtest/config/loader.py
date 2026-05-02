from pathlib import Path
from typing import Any

import yaml

from backtest.config.models import BacktestConfig


def load_config(path: str | Path) -> BacktestConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle)
    return BacktestConfig.model_validate(data)
