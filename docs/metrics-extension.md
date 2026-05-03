# Metrics Extension

## Built-In Metrics

Built-in metric names currently supported by `calculate_builtin_metrics()`:

```text
total_return
annualized_return
annualized_volatility
max_drawdown
sharpe_ratio
trade_count
cash_ratio
```

Config example:

```yaml
metrics:
  builtin:
    - total_return
    - max_drawdown
    - sharpe_ratio
```

Unknown built-in names are ignored by the current implementation.

## Custom Metrics

Custom metrics are loaded by `MetricRegistry.load_custom(path, class_name)`.
The class is instantiated with no constructor arguments and must expose
`calculate(context)`.

Config example:

```yaml
metrics:
  custom:
    - path: metrics/my_metric.py
      class: MyMetric
```

Metric example:

```python
from backtest.core.enums import MetricResultKind
from backtest.metrics.results import MetricResult


class MyMetric:
    name = "custom_score"

    def calculate(self, context):
        return MetricResult(
            name=self.name,
            kind=MetricResultKind.SCALAR,
            value=123,
        )
```

## MetricResult Kinds

`MetricResult.kind` must be one of:

```text
scalar
series
table
```

Use `scalar` for single values, `series` for time-indexed output, and `table`
for row/column diagnostics. `metrics.json` serializes Pydantic models and common
numeric scalar values, including NumPy scalar values.

## Context Available To Metrics

`BacktestResultContext` provides:

```text
equity_curve
positions
trades
orders
bars
config
```

Keep metrics independent from data providers. Metrics should consume result
frames and config, not fetch raw market data or infer cache paths.
