from datetime import UTC, datetime
from pathlib import Path
import hashlib
import re

import pandas as pd

from backtest.broker.engine import BrokerEngine
from backtest.config.models import BacktestConfig
from backtest.core.frames import validate_bar_frame
from backtest.metrics.builtin import calculate_builtin_metrics
from backtest.metrics.context import BacktestResultContext
from backtest.metrics.registry import MetricRegistry
from backtest.reports.manifest import build_manifest
from backtest.reports.writer import FileReportWriter
from backtest.signals.context import StrategyContext
from backtest.signals.providers import FileSignalProvider, PythonSignalProvider


class BacktestEngine:
    def __init__(
        self,
        config: BacktestConfig,
        config_path: Path,
        bars_override: pd.DataFrame | None = None,
    ) -> None:
        self.config = config
        self.config_path = Path(config_path)
        self.bars_override = bars_override

    def run(self) -> Path:
        bars = self._load_bars()
        signals = self._load_signals(bars)
        broker_result = BrokerEngine(self.config.execution).run(bars, signals)
        context = BacktestResultContext(
            equity_curve=broker_result.equity_curve,
            positions=broker_result.positions,
            trades=broker_result.trades,
            orders=broker_result.orders,
            bars=bars,
            config=self.config.model_dump(mode="json"),
        )
        metrics = calculate_builtin_metrics(context, self.config.metrics.builtin)
        metrics.update(self._calculate_custom_metrics(context))
        run_id = self._run_id()
        manifest = build_manifest(
            run_id=run_id,
            project_name=self.config.project.name,
            config_path=self.config_path,
            config_hash=self._file_hash(self.config_path),
            signal_source=self.config.signals.type,
            data_source=self.config.data.source,
            symbols=self.config.data.stock_pool.symbols,
            start_date=self.config.data.start_date,
            end_date=self.config.data.end_date,
        )
        return FileReportWriter(self.config.report.output_dir).write(
            run_id,
            broker_result,
            metrics,
            manifest,
        )

    def _load_bars(self) -> pd.DataFrame:
        if self.bars_override is None:
            raise ValueError("BacktestEngine requires cached bar loading to be wired by CLI data task")
        bars = validate_bar_frame(self.bars_override)
        if bars.empty:
            raise ValueError("No bar data available for backtest; sync cached data before running")
        return bars

    def _load_signals(self, bars: pd.DataFrame) -> pd.DataFrame:
        stock_pool = self.config.data.stock_pool.symbols
        if self.config.signals.type == "file":
            return FileSignalProvider(self.config.signals.path).load(stock_pool=stock_pool)

        context = StrategyContext(
            bars=bars,
            stock_pool=stock_pool,
            start_date=self.config.data.start_date.isoformat(),
            end_date=self.config.data.end_date.isoformat(),
            params={},
        )
        return PythonSignalProvider(self.config.signals.path, self.config.signals.function).load(context=context)

    def _run_id(self) -> str:
        slug = re.sub(r"[^A-Za-z0-9_-]+", "_", self.config.project.name).strip("_")
        if not slug:
            slug = "backtest"
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        return f"{slug}_{timestamp}"

    def _calculate_custom_metrics(self, context: BacktestResultContext) -> dict:
        registry = MetricRegistry()
        for metric_config in self.config.metrics.custom:
            path = metric_config.get("path")
            class_name = metric_config.get("class") or metric_config.get("class_name")
            if path is None or class_name is None:
                raise ValueError("Custom metric config requires 'path' and 'class'")
            registry.load_custom(path, class_name)
        return registry.calculate(context)

    def _file_hash(self, path: Path) -> str:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
