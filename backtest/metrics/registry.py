from importlib import util
from pathlib import Path
from types import ModuleType
from typing import Protocol
from uuid import uuid4

from backtest.metrics.context import BacktestResultContext
from backtest.metrics.results import MetricResult


class Metric(Protocol):
    name: str

    def calculate(self, context: BacktestResultContext) -> MetricResult:
        ...


class MetricRegistry:
    def __init__(self) -> None:
        self._metrics: list[Metric] = []

    def register(self, metric: Metric) -> None:
        self._metrics.append(metric)

    def load_custom(self, path: str | Path, class_name: str) -> None:
        module_path = Path(path)
        module = _load_module(module_path)
        try:
            metric_class = getattr(module, class_name)
        except AttributeError as exc:
            raise ValueError(f"Custom metric class '{class_name}' was not found in {module_path}") from exc
        self.register(metric_class())

    def calculate(
        self,
        context: BacktestResultContext,
    ) -> dict[str, MetricResult]:
        results: dict[str, MetricResult] = {}
        for metric in self._metrics:
            result = metric.calculate(context)
            results[result.name] = result
        return results


def _load_module(path: Path) -> ModuleType:
    module_name = f"backtest_custom_metric_{path.stem}_{uuid4().hex}"
    spec = util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load custom metric module from {path}")

    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
