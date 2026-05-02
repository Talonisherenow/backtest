# A 股回测系统设计

日期：2026-05-03
状态：等待用户审阅
工作目录：`/Users/talon/code/backtest`

## 1. 目标

搭建一套本地优先、研究优先的 A 股回测系统。第一版以 Python package 加 CLI 的形式交付，让用户可以：

- 爬取并缓存 A 股 OHLCV 行情数据。
- 记录本地已经存储了哪些股票、哪些频率、哪些时间范围的数据。
- 查询和管理数据爬取任务，支持进度追踪、失败记录和重试。
- 从 Python 策略代码或 CSV/Parquet 信号文件接收交易信号。
- 在可配置的 A 股交易假设下执行信号。
- 使用内置指标和自定义指标评估策略表现。
- 导出结构化结果和图表报告。
- 保留清晰扩展点，方便以后接入新数据源、新信号格式、新撮合模型、新评价体系和 GUI 展示层。

第一版不做多用户平台，也不追求大而全。它应该是一套边界清楚、能快速用于本地研究的回测工具。

## 2. 范围

### MVP 包含

- Python package 和 CLI。
- 日线数据作为第一版支持的主要频率。
- 所有核心接口保留 `frequency` 概念，方便以后扩展分钟线。
- 可插拔数据源接口。
- 默认 AkShare 数据源适配器。
- 使用 Parquet 缓存行情数据。
- 使用 SQLite 保存数据目录和爬取任务状态。
- 支持用户自定义股票池。
- 数据契约中支持不复权、前复权、后复权，研究场景默认建议前复权。
- 支持从 Python 策略函数生成信号。
- 支持从 CSV/Parquet 文件读取信号。
- 内部统一使用 `SignalFrame` 信号格式。
- 可配置成交时点，默认信号日后下一交易日开盘成交。
- 支持 A 股基础交易约束。
- 内置核心绩效指标。
- 支持自定义指标注册。
- 输出结构化结果文件和 HTML/图表报告。
- 交付可持续维护的文档，方便未来用户和未来模型会话理解系统。

### MVP 不包含

- 默认支持全 A 股范围回测。
- 完整交互式 GUI。
- 生产级任务队列或分布式爬虫。
- Tick 级或完整分钟级撮合引擎。
- 成交量参与率、市场冲击成本或复杂部分成交模拟。
- 投资组合优化器。
- 实盘交易。

这些能力作为未来扩展，不进入第一版范围。

## 3. 已确认设计决策

- 产品形态：Python package 加 CLI。
- 主要用途：本地量化研究和可复现策略回测。
- 数据频率：第一版日线优先，但接口支持未来扩展分钟线。
- 数据源：可插拔数据源，默认实现 AkShare。
- 存储：行情数据使用 Parquet，元数据和爬取任务使用 SQLite。
- 信号输入：同时支持 Python 策略函数和 CSV/Parquet 信号文件。
- 内部信号格式：统一 `SignalFrame`。
- 成交时点：可配置，默认信号日后下一交易日开盘成交。
- 交易约束：支持 A 股基础规则，包括 T+1、100 股一手、手续费、印花税、滑点、停牌、涨跌停限制。
- 股票范围：MVP 以自定义股票池为目标。
- 绩效输出：核心指标加图表报告。
- 自定义评价：支持指标注册机制和自定义指标接口。
- GUI：MVP 不做交互式 GUI，但报告和指标输出必须适合未来 GUI 读取和嵌入。

## 4. 总体架构

核心流程：

```text
DataProvider -> CrawlTaskManager -> BarStore -> SignalProvider -> Broker -> Metrics -> Reports
                                      |
                                      v
                                  DataCatalog
```

建议包结构：

```text
backtest/
  data/        数据源、数据目录、爬取任务、Parquet 行情缓存
  signals/     Python/文件信号源、SignalFrame 校验
  broker/      撮合模型、账户、持仓、订单、A 股交易约束
  metrics/     内置指标、自定义指标注册
  reports/     结构化导出、图表、HTML 报告
  cli/         命令行入口
  config/      YAML 配置模型和校验
```

MVP 要保持模块化。每个模块应该暴露稳定契约，并隐藏内部实现细节。

## 5. 扩展点

### DataProvider

负责从外部数据源获取行情数据。

第一版实现：

- `AkShareProvider`

未来可扩展：

- `TushareProvider`
- `LocalFileProvider`
- 其他商业数据源适配器

预期接口：

```python
class DataProvider:
    def fetch_bars(self, request: BarRequest) -> BarFrame:
        ...
```

### BarStore

负责读写本地行情缓存。

第一版实现：

- `ParquetBarStore`

未来可扩展：

- DuckDB 查询层
- 数据库型存储
- 远程对象存储

### SignalProvider

负责读取或生成交易信号。

第一版实现：

- `PythonSignalProvider`
- `FileSignalProvider`

未来可扩展：

- Notebook 导出适配器
- 因子模型适配器
- 机器学习模型适配器

### ExecutionModel

负责把标准化信号转换成订单和成交。

默认规则：

- T 日产生信号。
- 下一交易日开盘成交。

未来可扩展：

- 当日收盘成交。
- 下一交易日收盘成交。
- 分钟线撮合。
- 成交量约束撮合。

### CostModel 和 SlippageModel

手续费、税费和滑点逻辑独立于订单生成主流程。

这样可以避免把市场假设硬编码到撮合循环里。

### Metric 和 MetricRegistry

允许用户在不修改核心绩效模块的情况下扩展策略评价体系。

指标结果分为三类：

- `scalar`：单个数值，例如夏普比率。
- `series`：时间序列，例如滚动收益。
- `table`：表格结果，例如交易级诊断。

### ReportWriter

允许报告输出到不同目标。

第一版实现：

- `FileReportWriter`
- `HtmlReportWriter`

未来可扩展：

- Streamlit 应用
- Dash/Plotly 应用
- Panel 应用
- Web API 响应
- 数据库写入

## 6. 数据设计

### BarFrame

内部行情数据格式的必填字段：

```text
date
symbol
open
high
low
close
volume
amount
frequency
adjust
```

可选字段：

```text
pre_close
pct_change
turnover
is_suspended
limit_up
limit_down
source
updated_at
```

### 股票代码格式

系统内部统一使用标准 A 股代码：

```text
000001.SZ
600519.SH
```

数据源适配器可以接收各自数据源的原始代码格式，但返回给系统其他模块前必须完成标准化。

### 频率

MVP 支持：

```text
1d
```

接口和 schema 预留未来支持：

```text
1m
5m
15m
30m
60m
```

### 复权方式

支持值：

```text
none
qfq
hfq
```

MVP 推荐默认值：

```text
qfq
```

### Parquet 缓存目录

推荐目录结构：

```text
data/
  bars/
    frequency=1d/
      adjust=qfq/
        symbol=000001.SZ/
          year=2024/
            bars.parquet
```

这种结构适合大规模时间序列数据，也为以后按频率、复权方式、股票和年份分区保留空间。

## 7. 数据目录和爬取任务管理

系统需要正式的元数据层，不能只靠扫描文件夹推断状态。

### 元数据存储

使用 SQLite：

```text
data/
  metadata.sqlite
```

这个数据库保存数据目录记录和爬取任务生命周期状态。

### DataCatalog

记录本地数据覆盖情况。

代表字段：

```text
symbol
frequency
adjust
start_date
end_date
rows
source
cache_path
updated_at
quality_status
```

它必须能回答：

- 本地缓存了哪些股票？
- 每个股票、频率、复权方式覆盖了哪个日期范围？
- 当前请求中哪些股票缺少哪些时间段？
- 某个股票对应哪些缓存文件？
- 某个股票最后一次更新时间是什么时候？

### CrawlTaskManager

记录数据爬取任务和重试状态。

代表字段：

```text
task_id
symbol
frequency
adjust
start_date
end_date
source
status
attempts
last_error
created_at
updated_at
started_at
finished_at
```

任务状态：

```text
pending
running
success
failed
cancelled
retrying
```

这个组件用于支持进度可见、失败追踪和失败任务重试。

### 数据 CLI 命令

设计上支持：

```bash
backtest data sync --config configs/demo.yaml
backtest data inventory
backtest data coverage --config configs/demo.yaml
backtest data tasks
backtest data retry --failed
```

## 8. 信号设计

### SignalFrame

所有信号输入都会转成标准化 `SignalFrame`。

必填字段：

```text
date
symbol
target_weight
```

可选字段：

```text
signal_time
rebalance_group
priority
reason
```

`target_weight` 表示在配置的成交时点，该股票应该占组合总资产的目标比例。

MVP 约束：

- 不支持做空。
- `target_weight` 必须在 `0` 到 `1` 之间。
- 单个信号日的目标仓位总和不能超过 `1`。
- 除非显式允许，否则信号股票必须属于配置的股票池。
- 重复的 `date + symbol` 信号默认非法，除非配置了明确聚合规则。

### Python 策略输入

预期形式：

```python
def generate_signals(context) -> pandas.DataFrame:
    ...
```

策略上下文提供：

- 行情数据访问能力。
- 股票池。
- 日期范围。
- 当前配置。
- 用户自定义参数。

### 文件信号输入

CSV 和 Parquet 文件必须符合 `SignalFrame` schema。

示例：

```text
date,symbol,target_weight
2025-01-02,000001.SZ,0.10
2025-01-02,600519.SH,0.20
2025-01-03,000001.SZ,0.00
```

文件信号源是接入已有模型或外部信号流水线的主要桥梁。

## 9. 撮合设计

撮合模块把目标仓位转换成可执行订单和成交记录。

默认流程：

```text
读取 T 日信号
确定执行日期和执行价格
计算目标市值
和当前持仓对比
生成买卖订单
应用交易约束、费用模型和滑点模型
更新现金、持仓、订单、成交和每日净值
```

### 默认成交时点

```text
信号日 T -> 下一交易日开盘
```

这个默认规则可以避免不小心使用同日收盘价造成未来函数。

### A 股交易约束

MVP 支持：

- T+1 卖出限制。
- 买入按 100 股一手取整。
- 现金不能为负。
- 不能卖出超过可用持仓的数量。
- 佣金。
- 最低佣金。
- 卖出印花税。
- 滑点。
- 停牌股票不能交易。
- 涨停股票默认不能买入。
- 跌停股票默认不能卖出。

### 订单和成交记录

订单需要保留被拒绝或被调整前后的意图。

代表字段：

```text
date
symbol
side
requested_shares
filled_shares
price
commission
tax
slippage_cost
status
reason
```

被拒绝或被调整的订单必须能在报告里看到。

## 10. 指标与评价设计

绩效模块基于以下数据计算结果：

- 资金曲线。
- 日收益率。
- 持仓。
- 成交。
- 订单。
- 行情数据。
- 配置。

### 内置指标

MVP 内置：

```text
total_return
annualized_return
annualized_volatility
max_drawdown
sharpe_ratio
win_rate
profit_loss_ratio
turnover
trade_count
avg_holding_days
cash_ratio
```

如果配置了基准指数，额外支持：

```text
benchmark_return
excess_return
tracking_difference
```

### 自定义指标

自定义指标实现稳定接口：

```python
class Metric:
    name: str

    def calculate(self, context: BacktestResultContext) -> MetricResult:
        ...
```

配置示例：

```yaml
metrics:
  builtin:
    - total_return
    - max_drawdown
    - sharpe_ratio
  custom:
    - path: strategies/metrics.py
      class: MyCustomMetric
```

这样以后可以支持信号后 N 日收益、交易级诊断、滚动风险指标、自定义评分体系等评价方式，而不需要修改核心回测引擎。

## 11. 报告与 GUI 兼容性

MVP 不做交互式 GUI，但必须以适合未来 GUI 读取的方式导出结果。

每次回测输出：

```text
runs/
  20260503_153000_my_strategy/
    config.yaml
    manifest.json
    metrics.json
    custom_metrics/
    equity_curve.parquet
    positions.parquet
    trades.parquet
    orders.parquet
    report.html
    charts/
      equity_curve.png
      drawdown.png
      monthly_returns.png
```

HTML 报告包含：

- 策略和运行元数据。
- 核心指标卡片。
- 资金曲线。
- 回撤图。
- 月度收益图。
- 交易摘要。
- 被拒绝或被调整订单的摘要。
- 可展示的自定义指标结果。

未来 GUI 可以直接读取这些结构化文件：

- Streamlit。
- Dash 和 Plotly。
- Panel。
- 自定义 Web 前端。

第一版避免把回测引擎绑定到某个具体 GUI 框架。

## 12. Run Manifest

每次回测都应该包含 `manifest.json`，用于保证结果可追溯。

代表字段：

```text
run_id
created_at
config_path
config_hash
strategy_path
strategy_hash
signal_source
data_source
data_frequency
adjust
symbols
start_date
end_date
benchmark
engine_version
```

这样未来用户或模型会话可以知道某个结果到底是用什么数据、什么配置、什么策略生成的。

## 13. 配置设计

使用 YAML 作为主要配置格式。

代表配置：

```yaml
project:
  name: demo_strategy

data:
  source: akshare
  frequency: 1d
  adjust: qfq
  start_date: "2020-01-01"
  end_date: "2025-12-31"
  stock_pool:
    symbols:
      - 000001.SZ
      - 600519.SH

signals:
  type: file
  path: signals/demo_signals.parquet

execution:
  timing: next_open
  initial_cash: 1000000
  commission_rate: 0.0003
  min_commission: 5
  stamp_tax_rate: 0.0005
  slippage_rate: 0.0005
  board_lot_size: 100

metrics:
  builtin:
    - total_return
    - annualized_return
    - max_drawdown
    - sharpe_ratio

report:
  output_dir: runs
  html: true
  charts: true
```

配置加载器需要在开始爬取或回测前校验字段类型、日期格式、枚举值和必填配置段。

## 14. CLI 设计

数据命令：

```bash
backtest data sync --config configs/demo.yaml
backtest data inventory
backtest data coverage --config configs/demo.yaml
backtest data tasks
backtest data retry --failed
```

回测命令：

```bash
backtest run --config configs/demo.yaml
backtest report --run runs/20260503_153000_demo_strategy
```

工具命令：

```bash
backtest validate config --config configs/demo.yaml
backtest validate signals --path signals/demo_signals.parquet
```

CLI 默认输出适合人阅读的内容，未来可以通过 `--json` 支持机器可读输出。

## 15. 文档交付物

MVP 需要包含稳定文档，方便未来模型会话和人类用户快速理解、接入和操作框架。

### README.md

用途：

- 说明项目做什么。
- 展示安装和初始化流程。
- 提供最小端到端示例。
- 链接到更深入的文档。

### docs/architecture.md

用途：

- 解释模块边界。
- 展示数据流。
- 列出扩展点。
- 告诉未来模型会话应该在哪里改什么。

### docs/data-ingestion.md

用途：

- 解释如何爬取数据。
- 解释数据目录。
- 解释爬取任务、状态、重试和覆盖检查。
- 展示常见数据 CLI 工作流。

### docs/data-contracts.md

用途：

- 定义 `BarFrame`。
- 定义 `SignalFrame`。
- 定义订单、成交、持仓、资金曲线、指标结果和 run manifest schema。
- 解释已有 CSV/Parquet 数据如何转成系统可识别格式。

### docs/signal-integration.md

用途：

- 展示如何编写 Python 策略函数。
- 展示如何准备 CSV/Parquet 信号文件。
- 解释信号校验错误和修复方法。
- 解释外部模型应该如何导出信号。

### docs/metrics-extension.md

用途：

- 解释内置指标。
- 解释自定义指标接口。
- 展示如何在配置中注册自定义指标。
- 解释 `scalar`、`series`、`table` 三类指标结果。

### docs/reports.md

用途：

- 解释输出文件。
- 解释 HTML 报告内容。
- 解释未来 GUI 工具应该消费哪些文件。

### docs/cli.md

用途：

- 列出命令和示例。
- 解释预期输入输出。
- 包含排障提示。

### docs/ai-handoff.md

用途：

- 给未来模型会话提供短指南。
- 说明应该先阅读哪些文档。
- 总结关键契约和不变量。
- 提醒不要绕过 `SignalFrame`、`DataCatalog` 或配置校验。

未来模型会话推荐阅读顺序：

```text
README.md
docs/architecture.md
docs/data-contracts.md
docs/ai-handoff.md
```

## 16. 错误处理

预期错误类别：

- 配置非法。
- 数据源失败。
- 数据覆盖缺失。
- 缓存读写失败。
- 数据目录或任务元数据失败。
- 信号 schema 校验失败。
- 信号目标仓位非法。
- 交易约束导致订单拒绝。
- 报告生成失败。

数据爬取失败应该记录到任务表，并通过显式命令重试。

交易约束导致的拒单不应该让回测崩溃。它们应该写入订单输出，并带有清晰原因。

配置错误和信号 schema 错误应该在昂贵任务开始前快速失败。

## 17. 测试策略

MVP 至少覆盖：

- 配置校验。
- 股票代码标准化。
- `BarFrame` schema 校验。
- Parquet 缓存读写。
- `DataCatalog` 覆盖检查。
- `CrawlTaskManager` 生命周期和重试选择。
- `SignalFrame` 校验。
- 文件信号接入。
- Python 信号接入。
- 目标仓位转订单。
- T+1 卖出限制。
- 100 股一手取整。
- 佣金、最低佣金、印花税和滑点。
- 停牌、涨停、跌停拒单。
- 资金曲线生成。
- 内置指标计算。
- 自定义指标注册。
- 基于小型 fixture 数据的一次完整端到端回测。

测试应尽量使用小型、确定性的 fixture 数据，而不是依赖实时 AkShare 调用。

## 18. 风险和缓解

### 数据源不稳定

AkShare 可能因为上游接口变化而改变行为。

缓解：

- 隔离 `DataProvider`。
- 缓存已经获取的数据。
- 记录数据源和更新时间。
- 测试优先使用确定性 fixture。

### 未来函数风险

同日信号加同日收盘成交可能不小心引入未来函数。

缓解：

- 默认下一交易日开盘成交。
- 在配置和 manifest 中明确记录成交时点。

### 插件系统过度设计

过多抽象会拖慢 MVP。

缓解：

- 使用简单接口。
- 第一版只实现一个默认 provider/store/report writer。
- 只在高变化区域保留扩展点，不到处抽象。

### 元数据漂移

数据目录可能和 Parquet 文件不一致。

缓解：

- 按受控顺序写缓存和目录记录。
- 未来提供 reconcile 命令。
- 保存行数和缓存路径。

## 19. MVP 实现默认选型

除非实现阶段发现明确阻碍，否则使用以下默认方案：

- 使用 pandas 作为主要内部表格引擎，因为它是本地量化研究中最熟悉的选择，也能顺畅接入 CSV/Parquet 工作流。
- 使用 Typer 做 CLI，因为它能用较少样板代码提供清晰命令、类型参数和帮助信息。
- 使用 Pydantic 做配置和 schema 校验，让错误在爬取或回测开始前就能明确暴露。
- 使用 Plotly 做第一版 HTML 图表，因为未来 GUI 层可以复用同类交互图表模型。
- 只有在必要图片导出依赖可用时，才支持静态 PNG 导出。
- 实现 AkShare 适配器前，需要验证当前 AkShare 日线 A 股接口行为，因为上游数据 API 可能变化。

## 20. 通过标准

当用户确认以下内容后，设计可以进入实现计划阶段：

- 模块边界正确。
- 数据目录和爬取任务管理属于 MVP。
- 文档交付物足以支持未来使用和后续模型接手。
- GUI 延后，但输出保持 GUI 友好。
- 第一版优先追求正确性和清晰度，而不是平台复杂度。
