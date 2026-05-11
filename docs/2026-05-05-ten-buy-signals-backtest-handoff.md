# 2026-05-05 十大买讯回测能力交接

这份文档给未来新开的对话使用。它总结本轮对话中已经完成的事情、项目新增能力、关键文件位置，以及后续如何继续取数、看图、跑回测和分析结果。

注意：本文档记录的是 2026-05-05 的 legacy 十大买讯回测交接，当时主路径是
`BacktestEngine -> PythonSignalProvider -> BrokerEngine`。当前目标架构已补充
`SignalGenerator -> PortfolioAllocator -> StrategyPlanner` 和
`BacktestRunner -> ExecutionBackend`；十大买讯后续可以先通过
`LegacyStrategyPlanner` 适配进新 runtime，再逐步改写成原生 `SignalGenerator`。

2026-05-11 更新：当前最新分支交接以
`docs/2026-05-11-strategy-planning-architecture-handoff.md` 为准。本文档仍保留
十大买讯原始 legacy 跑法、样本数据和旧结果位置，便于对照迁移。

## 当前分支状态

本节记录的是当时 `feat/a-share-backtest-mvp` 分支上的历史状态。和那轮工作直接相关的提交顺序如下：

```text
bed842d feat: add fixed holding exits for buy signals
be19a89 feat: add all A-share universe sampling
10c6b8a feat: add reusable k-line viewer
b6c701c feat: add ten buy signal backtest results
```

如果新会话要继续处理当前策略架构分支，先运行：

```bash
git status --short --branch
git log --oneline --decorate -n 8
```

注意：仓库里可能还有未提交的临时图表，例如 `runs/charts/000002_SZ_kline_300d.html` 和 `.svg`。这些不是本轮已提交能力的必要文件，除非用户明确要求，不要混入后续提交。

## 本轮已经完成的事情

### 1. 十大买讯策略 case

根据 `docs/0504-十大买讯对应的量化公式.md`，项目里已经有 10 条买讯的策略实现和说明：

- 原始规则：`docs/0504-十大买讯对应的量化公式.md`
- 规则到代码映射：`docs/ten-buy-signals-implementation.md`
- 策略代码：`strategies/ten_buy_signals.py`
- 策略测试：`tests/strategies/test_ten_buy_signals.py`
- 基础 case：`configs/ten_buy_signals/*.yaml`

策略函数输出项目标准信号：

```text
date, symbol, target_weight
```

其中 `target_weight > 0` 表示买入或调仓到目标仓位，`target_weight = 0` 表示退出。

### 2. 固定持有期退出

十大买讯原始定义只有买入策略，没有退出策略。为了先验证买讯本身有效性，项目新增了固定持有期退出包装函数，覆盖 1、5、20 个交易日：

```text
generate_buy_signal_01_hold_1
generate_buy_signal_01_hold_5
generate_buy_signal_01_hold_20
...
generate_buy_signal_10_hold_1
generate_buy_signal_10_hold_5
generate_buy_signal_10_hold_20
```

实现位置在 `strategies/ten_buy_signals.py`：

- `FIXED_HOLDING_DAYS = (1, 5, 20)`
- `_signals_with_fixed_holding()`
- `_make_fixed_holding_generator()`

退出语义：

```text
买讯信号日 S
下一交易日 B 以 next_open 买入
持有 N 个交易日，B 算第 1 天
第 N 个持有交易日 H 生成 target_weight = 0
H 的下一交易日以 next_open 卖出
```

如果同一只股票尚未完成上一笔固定持有退出，又触发新的买讯，包装逻辑会忽略重叠入场，避免同一持仓周期重复买入。

### 3. A 股全市场股票池

项目支持通过 AkShare 获取当前全板块 A 股列表，包含上交所、深交所、北交所相关 A 股板块。

能力入口：

- 实现：`backtest/data/universe.py`
- CLI：`backtest data universe`
- 文档：`docs/data-ingestion.md`

生成全市场股票池：

```bash
backtest data universe --output data/universe/a_share_all.csv
```

本轮已生成并提交的股票池：

```text
data/universe/a_share_all_20260504.csv
```

标准字段：

```text
symbol, code, name, exchange, board, list_date, industry
```

`symbol` 使用项目标准格式，例如 `.SH`、`.SZ`、`.BJ`。

### 4. 随机样本和缓存行情

为了快速验证策略，按 `exchange + board` 分组，每组随机抽取 20 支，共 100 支样本股，取最近 300 个交易日的日 K。

本轮核心样本文件：

```text
data/universe/board_sample_20_each_20260504_seed42_clean.csv
data/universe/board_sample_20_each_20260504_seed42_clean.txt
data/universe/board_sample_20_each_20260504_seed42_clean_bar_coverage.csv
```

对应缓存行情：

```text
data/bars/frequency=1d/adjust=qfq/symbol=*/year=*/bars.parquet
```

本轮已验证口径：

```text
样本股票数：100
交易日区间：2025-02-07 至 2026-04-30
每只股票：300 根日 K
总行情行数：30000
```

读取缓存行情时使用 `ParquetBarStore`，不要手写分区路径扫描逻辑：

```python
from datetime import date
from pathlib import Path

from backtest.core.enums import AdjustMode, Frequency
from backtest.data.store import ParquetBarStore

symbols = Path("data/universe/board_sample_20_each_20260504_seed42_clean.txt").read_text().splitlines()
bars = ParquetBarStore("data/bars").read_bars(
    symbols=symbols,
    start_date=date(2025, 2, 7),
    end_date=date(2026, 4, 30),
    frequency=Frequency.DAILY,
    adjust=AdjustMode.QFQ,
)
```

### 5. K 线查看器

项目新增可复用的静态 K 线查看器，支持切换股票、搜索代码/名称、按板块过滤、交互缩放，并已经处理了两个重要显示问题：

- x 轴使用交易日类别轴，去掉周末和节假日空隙；
- 图例位置和标题错开；
- 价格纵轴保留 2 位小数。

能力入口：

- 实现：`backtest/charts/kline_viewer.py`
- CLI：`backtest chart viewer`
- 测试：`tests/charts/test_kline_viewer.py`
- 文档：`docs/cli.md`

生成查看器示例：

```bash
backtest chart viewer \
  --bars-root data/bars \
  --universe data/universe/board_sample_20_each_20260504_seed42_clean.csv \
  --symbols-file data/universe/board_sample_20_each_20260504_seed42_clean.txt \
  --output runs/charts/kline_viewer.html \
  --limit 300
```

输出 HTML 是自包含文件，可直接用 `file://` 打开。

### 6. 十大买讯 30 个回测 case

本轮生成了 30 个 case：

```text
10 个买讯 × 3 个固定持有期 = 30 个回测 case
```

配置位置：

```text
configs/ten_buy_signals/board_sample_20_each_300d/hold_1/*.yaml
configs/ten_buy_signals/board_sample_20_each_300d/hold_5/*.yaml
configs/ten_buy_signals/board_sample_20_each_300d/hold_20/*.yaml
```

每个配置使用：

- `source: cache`
- `frequency: 1d`
- `adjust: qfq`
- `stock_pool.symbols_file` 指向 100 支 clean 样本；
- `signals.path` 指向 `strategies/ten_buy_signals.py`；
- `signals.function` 指向对应的 `generate_buy_signal_XX_hold_N`；
- `execution.timing: next_open`。

本轮结果位置：

```text
runs/ten_buy_signals/board_sample_20_each_300d/
```

关键产物：

```text
summary.csv
summary.json
summary_dashboard.html
return_ranking.svg
return_heatmap.svg
run_metadata.json
failures.json
hold_*/buy_signal_*/*/report.html
hold_*/buy_signal_*/*/metrics.json
hold_*/buy_signal_*/*/orders.parquet
hold_*/buy_signal_*/*/trades.parquet
hold_*/buy_signal_*/*/equity_curve.parquet
hold_*/buy_signal_*/*/positions.parquet
```

已经验证：

```text
case 配置数：30
回测报告数：30
失败 case：0
summary 行数：30
```

### 7. 可视化结果页

用户希望看到类似收益排名的更好可视化。本轮基于 `summary.csv` 生成了静态结果页：

```text
runs/ten_buy_signals/board_sample_20_each_300d/summary_dashboard.html
```

页面内容：

- 收益最高/最低、正收益 case 数、最佳平均持有期；
- 总收益排名横向条形图；
- 买讯 × 持有期收益热力图；
- 持有期平均收益对比；
- Top 10 明细；
- 全部 30 个 case 的报告链接。

单独 SVG：

```text
runs/ten_buy_signals/board_sample_20_each_300d/return_ranking.svg
runs/ten_buy_signals/board_sample_20_each_300d/return_heatmap.svg
```

这两个 SVG 和 HTML 都是静态文件，不依赖外部服务。

## 如何复用这些能力

### 查看本轮结果

直接打开：

```text
runs/ten_buy_signals/board_sample_20_each_300d/summary_dashboard.html
```

或查看 CSV：

```bash
python - <<'PY'
import pandas as pd

summary = pd.read_csv("runs/ten_buy_signals/board_sample_20_each_300d/summary.csv")
print(summary.sort_values("total_return", ascending=False)[[
    "signal_id",
    "signal_slug",
    "holding_days",
    "entry_signal_rows",
    "trades",
    "total_return",
    "max_drawdown",
    "sharpe_ratio",
]].head(10).to_string(index=False))
PY
```

### 读取单个 case 结果

每个 `summary.csv` 行都有 `run_dir` 和 `report_path`。

```python
import pandas as pd
from pathlib import Path

summary = pd.read_csv("runs/ten_buy_signals/board_sample_20_each_300d/summary.csv")
case = summary.sort_values("total_return", ascending=False).iloc[0]
run_dir = Path(case["run_dir"])

metrics = pd.read_json(run_dir / "metrics.json", typ="series")
trades = pd.read_parquet(run_dir / "trades.parquet")
orders = pd.read_parquet(run_dir / "orders.parquet")
equity = pd.read_parquet(run_dir / "equity_curve.parquet")
```

### 新增一个持有期

如果用户要观测例如 10 日或 60 日持有：

1. 在 `strategies/ten_buy_signals.py` 中把 `FIXED_HOLDING_DAYS` 加上目标天数。
2. 补充或扩展测试，确认会自动生成 `generate_buy_signal_XX_hold_N`。
3. 生成对应 YAML 配置，`signals.function` 指向新函数。
4. 用缓存行情和 `BacktestEngine(..., bars_override=bars)` 跑批。

### 换一批股票或更长数据

标准流程：

```bash
backtest data universe --output data/universe/a_share_all_YYYYMMDD.csv
backtest data sample-pool \
  --universe data/universe/a_share_all_YYYYMMDD.csv \
  --size 200 \
  --seed 42 \
  --output data/universe/sample_200_seed42.txt
```

然后写一个 config，让 `stock_pool.symbols_file` 指向新样本，并执行：

```bash
backtest data sync --config configs/your_config.yaml --metadata data/metadata.sqlite --bars-root data/bars
```

如果只需要复用已有缓存，则直接用 `ParquetBarStore.read_bars()` 读取指定股票和日期范围。

## 当前限制和注意事项

### direct `backtest run` 仍不是主要入口

`backtest run --config ...` 的命令形状存在，但 CLI 直接从缓存加载 bars 的 wiring 仍未完成。当前测试和本轮跑批使用：

```python
BacktestEngine(config, config_path=config_path, bars_override=bars).run()
```

所以未来新会话不要承诺直接 `backtest run` 能完成缓存行情回测，除非先实现并验证这条链路。

### 买讯 09 是临时代码近似

`generate_buy_signal_09` 当前把样本池前两个股票当作“板块龙头”，用它们同步走强来近似板块领涨。严肃验证板块联动时，需要接入真实行业/概念板块成分数据。

### 买讯 10 在本轮样本中没有触发

本轮 100 支、300 日样本下，买讯 10 三个持有期都没有入场信号，因此收益为 0。这不是代码失败，而是样本和参数下没有触发。

### 回测结果是探索性结果

本轮样本是随机抽样，不是全市场完整验证；300 个交易日也只是初步窗口。结果可以用于观察策略倾向，但不应视为稳定结论。

## 验证命令

本轮提交前跑过以下验证：

```bash
python - <<'PY'
from pathlib import Path
import json
import pandas as pd
from backtest.config.loader import load_config

root = Path.cwd()
config_root = root / "configs/ten_buy_signals/board_sample_20_each_300d"
configs = sorted(config_root.glob("hold_*/*.yaml"))
assert len(configs) == 30, len(configs)
for path in configs:
    cfg = load_config(path)
    assert cfg.data.stock_pool.symbols, path
    assert cfg.signals.path.exists(), cfg.signals.path

run_root = root / "runs/ten_buy_signals/board_sample_20_each_300d"
summary = pd.read_csv(run_root / "summary.csv")
failures = json.loads((run_root / "failures.json").read_text(encoding="utf-8"))
reports = sorted(run_root.glob("hold_*/buy_signal_*/*/report.html"))
assert len(summary) == 30, len(summary)
assert len(failures) == 0, failures
assert len(reports) == 30, len(reports)
for filename in ["summary_dashboard.html", "return_ranking.svg", "return_heatmap.svg"]:
    assert (run_root / filename).exists(), filename
print("case_configs=30")
print("summary_rows=30")
print("reports=30")
print("visualization=true")
PY

git diff --check
.venv/bin/pytest
```

验证结果：

```text
case_configs=30
summary_rows=30
reports=30
visualization=true
120 passed, 2 warnings
```

## 给未来新会话的建议

- 先读 `docs/ai-handoff.md`、本文档、`docs/ten-buy-signals-implementation.md`。
- 改策略前先看 `tests/strategies/test_ten_buy_signals.py`。
- 改取数能力前先看 `docs/data-ingestion.md` 和 `backtest/data/`。
- 改 K 线页面前先看 `backtest/charts/kline_viewer.py` 和 `tests/charts/test_kline_viewer.py`。
- 改报告或 dashboard 时，优先消费 `summary.csv`、`metrics.json`、`orders.parquet`、`trades.parquet`、`equity_curve.parquet`，不要解析 HTML 报告。
- 提交时继续避开 `.idea/`、`.DS_Store`、`__pycache__/` 和用户未明确要求的临时导出文件。
