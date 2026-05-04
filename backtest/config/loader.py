import csv
from pathlib import Path
from typing import Any

import yaml

from backtest.config.models import BacktestConfig
from backtest.core.symbols import normalize_symbol


def _resolve_relative_path(base_dir: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return base_dir / path


def _read_symbols_file(path: Path) -> list[str]:
    if path.suffix.lower() == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None or "symbol" not in reader.fieldnames:
                raise ValueError("stock_pool.symbols_file CSV must contain a symbol column")
            return [row["symbol"].strip() for row in reader if row.get("symbol", "").strip()]

    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _normalize_symbols(symbols: list[str]) -> list[str]:
    if not symbols:
        raise ValueError("stock_pool symbols file must not be empty")
    return [normalize_symbol(symbol) for symbol in symbols]


def load_config(path: str | Path) -> BacktestConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle)
    config = BacktestConfig.model_validate(data)
    base_dir = config_path.parent

    config.signals.path = _resolve_relative_path(base_dir, config.signals.path)
    config.report.output_dir = _resolve_relative_path(base_dir, config.report.output_dir)
    if config.data.stock_pool.symbols_file is not None:
        symbols_file = _resolve_relative_path(base_dir, config.data.stock_pool.symbols_file)
        config.data.stock_pool.symbols_file = symbols_file
        file_symbols = _read_symbols_file(symbols_file)
        config.data.stock_pool.symbols = _normalize_symbols([*config.data.stock_pool.symbols, *file_symbols])
    for custom_metric in config.metrics.custom:
        if "path" in custom_metric:
            custom_metric["path"] = str(_resolve_relative_path(base_dir, Path(custom_metric["path"])))

    return config
