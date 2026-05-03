import textwrap

import pandas as pd
import pytest

from backtest.core.enums import MetricResultKind
from backtest.metrics import BacktestResultContext, MetricRegistry
from backtest.metrics.results import MetricResult


def make_context() -> BacktestResultContext:
    return BacktestResultContext(
        equity_curve=pd.DataFrame({"equity": [100.0]}),
        positions=pd.DataFrame(),
        trades=pd.DataFrame(),
        orders=pd.DataFrame(),
        bars=pd.DataFrame(),
        config={},
    )


def test_registry_loads_custom_metric_class(tmp_path) -> None:
    metric_file = tmp_path / "custom_metric.py"
    metric_file.write_text(
        textwrap.dedent(
            """
            from backtest.core.enums import MetricResultKind
            from backtest.metrics.results import MetricResult


            class AnswerMetric:
                name = "answer"

                def calculate(self, context):
                    return MetricResult(
                        name=self.name,
                        kind=MetricResultKind.SCALAR,
                        value=42,
                    )
            """
        ),
        encoding="utf-8",
    )
    registry = MetricRegistry()

    registry.load_custom(metric_file, "AnswerMetric")
    results = registry.calculate(make_context())

    assert results["answer"] == MetricResult(
        name="answer",
        kind=MetricResultKind.SCALAR,
        value=42,
    )


def test_registry_registers_metric_object_and_keys_by_result_name() -> None:
    class DirectMetric:
        name = "declared_name"

        def calculate(self, context):
            return MetricResult(
                name="result_name",
                kind=MetricResultKind.SCALAR,
                value=7,
            )

    registry = MetricRegistry()

    registry.register(DirectMetric())
    results = registry.calculate(make_context())

    assert list(results) == ["result_name"]
    assert results["result_name"].value == 7


def test_registry_reports_path_and_class_when_custom_metric_class_is_missing(tmp_path) -> None:
    metric_file = tmp_path / "custom_metric.py"
    metric_file.write_text("class ExistingMetric:\n    pass\n", encoding="utf-8")
    registry = MetricRegistry()

    with pytest.raises(ValueError, match=r"MissingMetric.*custom_metric\.py"):
        registry.load_custom(metric_file, "MissingMetric")
