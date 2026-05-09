# AI Handoff

这份文档是新 AI 会话的第一入口。目标是让后续 AI 只读这一份，就能知道这个项目是什么、已经能做什么、关键文件在哪里、哪些能力可以复用、哪些地方还没打通，以及继续开发时应该遵守哪些边界。

## 一句话定位

这是一个本地研究型 A 股回测 MVP，`main` 已合入通用标的交易架构第一阶段地基，当前
`feat/crypto-market-data` 分支正在补加密货币历史行情接口。它不是多用户服务，而是一个 Python package + CLI，用来做可复现的策略研究，并为后续接入港股、美股、加密货币和真实交易 API 预留统一合同：

```text
配置 YAML -> 数据缓存 -> 信号生成 -> 模拟撮合 -> 指标计算 -> 结构化报告/可视化
```

通用交易架构目标链路：

```text
MarketDataProvider
  -> StrategyRunner
  -> TargetPortfolio / OrderIntent
  -> RiskGate
  -> OrderLedger
  -> ExecutionAdapter
  -> ExecutionReport
  -> PortfolioState
```

当前已经具备：

- A 股股票池获取和随机抽样；
- AkShare 日线数据同步；
- Parquet 行情缓存和 SQLite 元数据；
- CSV/Parquet/Python 策略信号接入；
- A 股规则相关的简化 Broker；
- 内置指标和自定义指标扩展；
- 结构化回测报告；
- 可复用 K 线查看器；
- 十大买讯策略、固定持有期退出、30 个回测 case 和可视化结果页；
- CCXT 加密货币现货历史 OHLCV 接入；
- `BTC/USDT` 这类 crypto spot symbol 和安全缓存路径；
- 加密货币代表性周期 `4h` 和 `1h`，旧 `60m` 输入会归一化为 `1h`；
- Market data sync jobs，把批量数据拉取沉淀为项目内 runner，而不是一次性终端脚本；
- Bitget 历史 OHLCV 请求会自动把 limit 限制到 200，避免 CCXT 分页时系统性跳过旧 K 线；
- K 线查看器支持多个 `--source-root label=path`，可在 Data Status 里切换当前数据源；
- 通用 `Instrument`、`TradingRule`、`TargetPortfolioFrame`；
- 通用 `OrderIntent`、`ExecutionReport`、`PortfolioState`；
- 独立 `OrderPlanner`；
- SQLite `OrderLedger`，按 `(account_id, client_order_id)` 隔离订单。

## 新会话建议阅读顺序

先读本文档，再按任务需要读更细文档和代码：

1. `README.md`
2. `docs/architecture.md`
3. `docs/data-contracts.md`
4. `docs/data-ingestion.md`
5. `docs/cli.md`
6. `docs/superpowers/specs/2026-05-09-kline-cache-viewer-design.md`
7. `docs/superpowers/specs/2026-05-07-universal-trading-architecture-design.md`
8. `docs/superpowers/plans/2026-05-07-universal-trading-architecture.md`
9. `docs/superpowers/specs/2026-05-08-crypto-market-data-design.md`
10. `docs/superpowers/plans/2026-05-08-crypto-market-data.md`
11. `docs/superpowers/specs/2026-05-09-market-data-sync-jobs-design.md`
12. `docs/superpowers/plans/2026-05-09-market-data-sync-jobs.md`
13. `docs/ten-buy-signals-implementation.md`
14. `docs/2026-05-05-ten-buy-signals-backtest-handoff.md`
15. 当前要改的代码和测试

旧设计文档在 `docs/superpowers/specs/` 下，可作为背景，但当前代码、测试和本文档优先级更高。

## 当前分支和近期能力

截至 2026-05-08，当前工作分支是：

```text
feat/crypto-market-data
```

该分支从已合并通用交易架构的 `main` 切出。A 股回测主能力仍可用；本分支新增的是 CCXT 加密货币历史行情接口，仍未接真实交易 API。

和本轮能力直接相关的提交：

```text
57f1276 fix: separate kline data status action
576ce9b fix: make kline viewer controls responsive
5148e59 fix: improve kline viewer data navigation
f891957 fix: simplify kline viewer status layout
05144f6 feat: add multi-frequency kline cache viewer
133a833 docs: design kline cache viewer
783bfff docs: plan crypto market data ingestion
5b8f79b feat: support crypto symbols in market data cache
d9de9fc feat: add ccxt crypto ohlcv provider
29b218b feat: wire ccxt market data sync
ee21167 feat: add universal instrument models
0f8263d feat: add target portfolio frame contract
237e6a6 feat: add order intent contracts
09e4e2c feat: add portfolio state models
aece6eb feat: convert legacy signals to target portfolios
8902fae feat: add target portfolio order planner
bb5818d feat: add sqlite order ledger
d955e3c docs: describe universal trading contracts
bed842d feat: add fixed holding exits for buy signals
be19a89 feat: add all A-share universe sampling
10c6b8a feat: add reusable k-line viewer
b6c701c feat: add ten buy signal backtest results
```

近期已经确认的产品和架构决策：

- 先接 CCXT 历史行情，真实交易 API 适配器后续再做；
- crypto 第一版只做现货 OHLCV，不做合约、实盘下单或 crypto 撮合器；
- crypto 代表性默认研究周期是 `1d + 4h + 1h`，短线扩展 `15m + 5m`，`1m` 只在需要执行细节时拉；
- 批量数据生产要走 `backtest data sync-job --job ...` 和 `MarketDataJobRunner`，不要把重要取数逻辑留在临时脚本里；
- 多账户能力要保留口子，第一版默认单账户 `default`；
- 订单、执行回报、组合状态、ledger 都必须带 `account_id`；
- CLI 单次触发是默认运行形态，但 runner 边界要能被未来守护进程复用；
- 策略和交易 API 解耦：策略只产出目标组合或订单意图，不直接调用 API。

新会话继续工作前先确认：

```bash
git status --short --branch
git log --oneline --decorate -n 8
```

注意：工作区可能有用户或临时产物，例如 `runs/charts/000002_SZ_kline_300d.html` 和 `.svg`。除非用户明确要求，不要把这类未跟踪临时文件混进提交。

## 项目主流程

架构主线：

```text
DataProvider -> DataSyncService -> ParquetBarStore
                         |              |
                         v              v
                  CrawlTaskManager   DataCatalog

Config -> BacktestEngine -> SignalProvider -> BrokerEngine -> Metrics -> Reports
```

回测执行主线：

1. `backtest.config.loader.load_config()` 读取 YAML，并解析相对路径。
2. `BacktestConfig` 等 Pydantic 模型校验配置。
3. 行情数据以标准 `BarFrame` 输入。
4. `FileSignalProvider` 或 `PythonSignalProvider` 生成标准 `SignalFrame`。
5. `BrokerEngine` 根据目标仓位信号进行 `next_open` 执行。
6. `calculate_builtin_metrics()` 和 `MetricRegistry` 计算指标。
7. `FileReportWriter` 写出 JSON、Parquet 和 HTML 报告。

当前重要限制：`backtest run --config ...` 的命令形状存在，但 CLI 直接从缓存加载 bars 仍未完全打通。现在可用且已验证的方式是用 `BacktestEngine(..., bars_override=bars)` 直接传入缓存行情。

## 目录地图

核心代码：

```text
backtest/cli/          Typer CLI
backtest/config/       YAML 加载和 Pydantic 配置模型
backtest/core/         枚举、符号规范化、BarFrame/SignalFrame 校验
backtest/data/         AkShare/CCXT provider、行情缓存、元数据、股票池、同步服务
backtest/signals/      CSV/Parquet/Python 信号 provider
backtest/broker/       账户、费用、滑点、执行循环、订单和成交结果
backtest/planning/     TargetPortfolio -> OrderIntent 规划器
backtest/portfolio/    多账户预留的组合状态模型
backtest/execution/    执行基础设施，目前有 SQLite OrderLedger
backtest/metrics/      内置指标、自定义指标 registry、结果上下文
backtest/reports/      manifest、结构化报告、HTML report
backtest/charts/       K 线查看器
strategies/            项目外部策略文件，目前包含十大买讯
configs/               示例和批量回测配置
data/                  股票池、metadata.sqlite、Parquet 行情缓存
runs/                  回测、图表和 dashboard 输出
tests/                 单元和端到端测试
docs/                  项目文档
```

关键文档：

```text
docs/architecture.md                             架构边界和主流程
docs/data-contracts.md                           symbol、BarFrame、SignalFrame 规范
docs/data-ingestion.md                           AkShare、股票池、缓存、metadata、sync
docs/signal-integration.md                       文件信号和 Python 策略信号
docs/metrics-extension.md                        内置指标和自定义指标
docs/reports.md                                  报告产物结构
docs/cli.md                                      当前 CLI 命令
docs/superpowers/specs/2026-05-09-kline-cache-viewer-design.md K 线缓存查看器设计
docs/superpowers/specs/2026-05-07-universal-trading-architecture-design.md 通用交易架构设计
docs/superpowers/plans/2026-05-07-universal-trading-architecture.md 通用交易架构第一阶段执行计划
docs/superpowers/specs/2026-05-08-crypto-market-data-design.md 加密货币历史行情接口设计
docs/superpowers/plans/2026-05-08-crypto-market-data.md 加密货币历史行情接口执行计划
docs/superpowers/specs/2026-05-09-market-data-sync-jobs-design.md 批量行情同步任务设计
docs/superpowers/plans/2026-05-09-market-data-sync-jobs.md 批量行情同步任务执行计划
docs/0504-十大买讯对应的量化公式.md              原始十大买讯公式
docs/ten-buy-signals-implementation.md           十大买讯公式到代码的映射
docs/2026-05-05-ten-buy-signals-backtest-handoff.md 本轮回测能力交接
```

## 数据和缓存能力

### 股票代码规范

全项目使用规范化 A 股 symbol：

```text
000001.SZ
600519.SH
430017.BJ
```

`normalize_symbol()` 接受裸 6 位代码和 `SZ000001`、`SH600519`、`BJ430017` 等形式，并转成规范 symbol。裸代码推断规则：

- `4`、`8` 开头：`.BJ`
- `5`、`6`、`9` 开头：`.SH`
- 其他：`.SZ`

### A 股全市场股票池

已支持通过 AkShare 获取当前全板块 A 股列表：

```bash
backtest data universe --output data/universe/a_share_all.csv
```

实现入口：

```text
backtest/data/universe.py
backtest/cli/data.py
```

标准输出字段：

```text
symbol, code, name, exchange, board, list_date, industry
```

本轮已生成：

```text
data/universe/a_share_all_20260504.csv
```

### 随机股票池

从 universe 中生成可复现随机样本：

```bash
backtest data sample-pool \
  --universe data/universe/a_share_all.csv \
  --size 200 \
  --seed 42 \
  --output data/universe/sample_200_seed_42.txt
```

当前已提交的核心样本：

```text
data/universe/board_sample_20_each_20260504_seed42_clean.csv
data/universe/board_sample_20_each_20260504_seed42_clean.txt
data/universe/board_sample_20_each_20260504_seed42_clean_bar_coverage.csv
```

该样本口径：

```text
按 exchange + board 分组，每组随机 20 支
共 100 支股票
日期区间：2025-02-07 至 2026-04-30
每支股票：300 根日 K
总行情行数：30000
```

### 行情缓存

行情缓存走 `ParquetBarStore`，不要在业务代码里手写目录扫描：

```text
data/bars/
  frequency=1d/
    adjust=qfq/
      symbol=000001.SZ/
        year=2025/
          bars.parquet
```

加密货币 symbol 带 `/`，缓存路径会做 percent encoding：

```text
data/bars/
  frequency=4h/
    adjust=none/
      symbol=BTC%2FUSDT/
        year=2025/
          bars.parquet
```

Parquet 行和 catalog 里的 symbol 仍是 `BTC/USDT`。

读取示例：

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

### Metadata 和同步

`data/metadata.sqlite` 保存两类状态：

- `catalog`：缓存覆盖范围、行数、路径、质量状态；
- `crawl_tasks`：抓取任务、重试次数、错误、任务状态。

常用命令：

```bash
backtest data coverage --config configs/demo.yaml --metadata data/metadata.sqlite
backtest data sync --config configs/demo.yaml --metadata data/metadata.sqlite --bars-root data/bars
backtest data inventory --metadata data/metadata.sqlite
backtest data tasks --metadata data/metadata.sqlite
backtest data retry --failed --metadata data/metadata.sqlite
```

批量数据生产使用 data job：

```bash
backtest data sync-job --job configs/data_jobs/crypto_bitget_core.yaml
```

第一份已提交 job 配置：

```text
configs/data_jobs/crypto_bitget_core.yaml
```

它会展开 `BTC/USDT`、`ETH/USDT`、`SOL/USDT`、`BNB/USDT` 与 `1d`、`4h`、
`1h`、`30m`、`15m`、`5m`、`1m` 的组合，复用 `DataSyncService` 执行每个
item。运行结果写到：

```text
runs/crypto_market_data/bitget_core/summary.csv
runs/crypto_market_data/bitget_core/summary.json
```

Bitget job 使用 exchange-scoped cache root：

```text
data/crypto/bitget/bars
data/crypto/bitget/metadata.sqlite
page_delay_seconds: 0.35
```

`data/crypto/` 和 `runs/crypto_market_data/` 是本地生成产物，除非用户明确要求，不要
stage 或提交。

`data sync` 当前支持：

- `source: akshare`：A 股日线，provider 是 `AkShareProvider`；
- `source: ccxt`：加密货币现货历史 OHLCV，provider 是 `CCXTOHLCVProvider`。

crypto 配置必须显式设置 `data.exchange`，例如：

```yaml
data:
  source: ccxt
  exchange: binance
  frequency: 4h
  adjust: none
  start_date: "2025-01-01"
  end_date: "2025-01-31"
  stock_pool:
    symbols:
      - BTC/USDT
```

catalog source 会写成 `ccxt:<exchange>`，例如 `ccxt:binance`，避免不同交易所缓存互相覆盖。

## 数据和信号契约

### BarFrame

必需列：

```text
date, symbol, open, high, low, close, volume, amount, frequency, adjust
```

可选执行列：

```text
is_suspended, limit_up, limit_down
```

所有行情写入前应通过 `validate_bar_frame()`，它会校验列、日期、symbol、枚举、数值、OHLC 合法性并排序。

允许的频率：

```text
1d, 1m, 5m, 15m, 30m, 1h, 4h
```

crypto OHLCV 约定：

- symbol 使用 CCXT unified spot symbol，例如 `BTC/USDT`；
- `adjust` 必须是 `none`；
- `date` 是 UTC 时间，保存为 timezone-naive pandas datetime；
- `volume` 是 CCXT 返回的成交量，通常是 base asset 数量；
- `amount` 第一版估算为 `close * volume`；
- `1h` 是标准一小时频率；旧 `60m` 输入会归一化为 `1h`；
- provider 默认丢弃当前未收盘 K 线。

### SignalFrame

必需列：

```text
date, symbol, target_weight
```

`target_weight` 是目标组合权重，不是订单方向或数量。它必须在 `[0, 1]` 内，同一天所有 symbol 权重总和不能超过 `1.0`。

所有策略或外部信号都应通过 `validate_signal_frame()`。不要绕过校验。

### 通用交易合同

本分支新增通用交易合同，但还没有把 `BrokerEngine` 改成实盘执行引擎。未来 AI 必须区分旧回测合同和新通用交易合同。

新增核心模型：

```text
backtest/core/instruments.py
  Market
  AssetClass
  Instrument
  TradingRule

backtest/core/targets.py
  TARGET_PORTFOLIO_COLUMNS
  validate_target_portfolio_frame()

backtest/core/orders.py
  OrderIntent
  ExecutionReport
  OrderSide
  OrderType
  TimeInForce
  ExecutionStatus

backtest/portfolio/state.py
  CashBalance
  PositionState
  PortfolioState

backtest/planning/order_planner.py
  OrderPlanner

backtest/execution/ledger.py
  SQLiteOrderLedger
```

核心语义：

```text
TargetPortfolio != OrderIntent
OrderIntent != ExecutionReport
ExecutionReport 才能更新 PortfolioState
```

`TargetPortfolioFrame` 必需列：

```text
timestamp, instrument_id, target_weight
```

`OrderIntent` 表示“系统想提交什么订单”，不是成交事实。关键字段：

```text
account_id, client_order_id, strategy_id, instrument_id, side,
quantity, order_type, limit_price, time_in_force, created_at, reason
```

`ExecutionReport` 表示“执行层发生了什么”，回测里由模拟撮合生成，实盘里未来由券商或交易所 API 返回。关键字段：

```text
account_id, client_order_id, instrument_id, status, order_quantity,
filled_quantity, avg_fill_price, reported_at, broker_order_id, error, raw_response
```

`PortfolioState` 是账户级组合状态：

```text
account_id, cash, positions, updated_at
```

`SQLiteOrderLedger` 使用 `(account_id, client_order_id)` 做主键。第一版默认 `account_id="default"`，但测试已经覆盖 `paper`、`live` 两个账户的订单隔离。

旧 `SignalFrame(date, symbol, target_weight)` 可以通过 `legacy_signals_to_target_portfolio()` 转成新 `TargetPortfolioFrame(timestamp, instrument_id, target_weight)`。这只是兼容桥，不代表旧策略已经直接支持实盘下单。

## 策略和信号接入

项目支持两类信号：

### 文件信号

CSV 或 Parquet：

```yaml
signals:
  type: file
  path: signals/demo.csv
```

校验：

```bash
backtest validate signals --path signals/demo.csv --symbol 000001.SZ
```

### Python 策略信号

策略文件放在 `backtest/` 核心包外，例如 `strategies/`：

```yaml
signals:
  type: python
  path: strategies/my_strategy.py
  function: generate_signals
```

函数接收 `StrategyContext`：

```text
bars
stock_pool
start_date
end_date
params
```

策略应返回标准 `SignalFrame`。不要让策略返回订单意图、手数或买卖 side。

## Broker 和执行能力

`BrokerEngine` 当前支持：

- `next_open` 执行；
- 目标权重调仓；
- A 股 board lot，默认 100 股；
- 佣金、最低佣金、印花税、过户费；
- 固定比例滑点；
- T+1 可卖限制；
- 停牌、涨停买入限制、跌停卖出限制；
- 输出 orders、trades、positions、equity curve。

注意：`BrokerEngine` 仍是 A 股回测撮合器，不是真实交易系统。通用交易架构第一阶段没有替换 `BrokerEngine`，只是新增了可以复用的交易合同和规划器。

新增执行相关能力：

- `OrderPlanner`：把 `TargetPortfolioFrame + PortfolioState + prices + TradingRule` 转成 `OrderIntent`；
- `OrderPlanner` 会从 `PortfolioState.account_id` 继承账户标识；
- `SQLiteOrderLedger`：记录订单意图和执行回报，主键为 `(account_id, client_order_id)`；
- `OrderIntent`、`ExecutionReport`、`PortfolioState` 都带 `account_id`，第一版默认单账户 `default`；
- `OrderIntent.client_order_id`、`account_id`、`strategy_id` 会保留调用方原始大小写，只去首尾空格；
- `instrument_id` 会标准化为大写。

当前不支持：

- `same_close` 或 `next_close` 执行；
- 分钟级撮合；
- 复杂订单类型；
- 真实资金费率或融资融券。
- 真实交易 API；
- `ExecutionAdapter`、`ExecutionRouter`、`RiskGate`；
- 多账户调度和多账户聚合视图。

新增 A 股回测撮合行为时改 `backtest/broker/` 并补测试。新增通用交易行为时优先扩展 `backtest/planning/`、`backtest/portfolio/`、`backtest/execution/`，不要把真实 API 调用塞进策略或 `BrokerEngine`。

下一阶段真实 API 适配器优先级：

```text
1. DryRunExecutionAdapter
2. CCXTExecutionAdapter
3. 后续再评估 Longbridge / QMT / IBKR
```

注意：当前已经有 `CCXTOHLCVProvider` 用于历史行情；这不是交易执行适配器。

实盘运行形态约定：

- CLI 单次触发是默认入口；
- 后续可以复用同一 runner 边界做守护进程循环；
- 现在不要承诺已有实盘守护进程。

## 指标能力

内置指标名：

```text
total_return
annualized_return
annualized_volatility
max_drawdown
sharpe_ratio
trade_count
cash_ratio
```

配置示例：

```yaml
metrics:
  builtin:
    - total_return
    - max_drawdown
    - sharpe_ratio
```

注意：旧草稿里可能出现 `sharpe`，当前有效名称是 `sharpe_ratio`。

自定义指标通过 `MetricRegistry.load_custom(path, class_name)` 加载，类需要提供 `calculate(context)`，返回 `MetricResult` 或可序列化结果。

## 报告和可视化消费约定

每次回测输出目录：

```text
<report.output_dir>/<safe_run_id>/
```

固定文件：

```text
manifest.json
metrics.json
equity_curve.parquet
positions.parquet
orders.parquet
trades.parquet
report.html
```

GUI、dashboard 或分析脚本应读取 JSON/Parquet，不要解析 `report.html`。

`report.html` 当前总是写出；`report.html` 和 `report.charts` 配置字段存在，但禁用 HTML 或自动图表产物还没完全实现。

## K 线查看器

已新增 K 线缓存查看器，包含两种形态：

- `backtest chart viewer` 生成自包含静态 HTML，适合 `file://` 打开和归档；
- `backtest chart serve` 启动只读本地服务，适合数据仍在补齐、需要按 symbol/frequency 动态读取本地窗口时使用。

```text
backtest/charts/kline_viewer.py
backtest/charts/kline_service.py
backtest/charts/kline_server.py
tests/charts/test_kline_viewer.py
tests/charts/test_kline_service.py
tests/charts/test_kline_cli.py
```

静态 HTML CLI：

```bash
backtest chart viewer \
  --bars-root data/bars \
  --universe data/universe/board_sample_20_each_20260504_seed42_clean.csv \
  --symbols-file data/universe/board_sample_20_each_20260504_seed42_clean.txt \
  --output runs/charts/kline_viewer.html \
  --limit 300
```

动态本地服务 CLI：

```bash
backtest chart serve \
  --bars-root data/crypto \
  --adjust none \
  --host 127.0.0.1 \
  --port 8765 \
  --window-size 5000
```

能力：

- 自包含 HTML，可直接 `file://` 打开，也可通过本地静态服务器预览；
- 动态服务模式页面通过 `/api/manifest` 获取本地全量数据索引，通过 `/api/bars` 按当前 source/symbol/frequency/window 拉取窗口数据；
- 动态服务只读最终 `bars.parquet` 文件，不写入 cache、metadata 或 crawl_tasks，可和正在运行的数据爬取任务并行；
- `chart viewer` 和 `chart serve` 在未传 `--source-root` 时会自动扫描 `--bars-root` 下的 `<source>/bars` 目录，例如 `data/crypto/bitget/bars` 会识别为 `Bitget`；
- 如果 source 不在统一父目录下，或需要自定义 label，可继续显式传多个 `--source-root label=path`；
- 自动从 Parquet cache 发现已爬取 symbol、frequency、adjust、years、行数和首尾时间；
- 同一 symbol 同一 frequency 的分散 year partition 会合并为一个序列展示，不按单文件拆开；
- 支持多时间级别切换，未指定 `--frequency` 时会发现 root 下所有可用级别；
- 支持 symbol 下拉、代码/名称搜索、Market / Board 过滤；
- crypto spot 默认归类为 `Crypto / Spot`，真正缺少市场和板块信息的标的才归到 `Unclassified`；
- 顶部筛选区只放 Market / Board、Symbol、Search、Frequency 这类筛选项，`Data Status` 是标题区右侧的独立全局入口；
- `Window`、`Overlap`、当前 rows 范围、`Older`、`Newer`、`Latest`、`Jump to` 和 `Position` 滑条放在单独的时间窗口工具条；
- `Data Status` 按钮显示 cached series 数量，点击后打开右侧抽屉；
- Data Status 抽屉按 symbol 分组，每组列出该 symbol 已缓存的所有 frequency；
- 可用多个 `--source-root label=path` 生成多数据源 viewer，Data Status 顶部会出现 source 切换入口；
- 切换 source 后，主页面 symbol 和 frequency 控件只展示当前 source 下的数据；
- 页面 header 和 summary 都会显示当前 source；
- 抽屉行展示首尾时间、rows、years、adjust，点击行会切到对应 symbol/frequency；
- `Window` 下拉控制当前图表窗口大小：`100`、`300`、`1000`、`5000`、`All available`；
- `Overlap` 下拉控制相邻 `Older`/`Newer` 窗口的交集，默认 80%；例如 `Window=5000`、`Overlap=80%` 时，每次点击移动 1000 根，保留 4000 根重叠；
- `Position` 滑条在静态模式里于已嵌入 bars 内前后移动，在动态模式里映射到当前 symbol/frequency 的全量本地 row offset；
- 动态模式会在后台多预取一段隐藏 buffer 来保证拖动流畅，但这个 buffer 不是用户可见的翻页单位；
- 动态模式下 `Older`/`Newer` 按 `window size * (1 - overlap)` 移动可见窗口，`Latest` 回到最新窗口；
- `Jump to` 输入框始终同步为当前可见窗口第一根 K 线开始时间；输入非 K 线边界时间时定位到包含该时间的 bar，例如 `5m` 输入 `10:02` 会落到 `10:00`；切换 frequency/window size 继续以当前 `Jump to` 为锚点，如果目标之后不足一个 window，就展示最后完整 window 并把 `Jump to` 改成实际窗口首根时间；
- `--limit 0` 表示每个 symbol/frequency 嵌入全量缓存 bars；非零 limit 只嵌入最近 N 根；
- 页面里只能浏览生成时已嵌入的 bars。若要看更早历史，必须用更大的 `--limit` 或 `--limit 0` 重新生成；
- 动态服务不需要重新生成 HTML；补完 parquet 后刷新页面或切换选择即可读取最新落盘数据；
- Plotly 图表可交互缩放；
- 使用交易日类别轴，去掉周末/节假日空隙；
- 图例不遮挡标题；
- 价格纵轴保留 2 位小数。

crypto 当前常用生成命令：

```bash
backtest chart viewer \
  --bars-root data/crypto/bitget/bars \
  --output runs/charts/crypto_kline_viewer.html \
  --limit 5000 \
  --adjust none
```

多数据源 viewer 示例：

```bash
backtest chart viewer \
  --source-root bitget=data/crypto/bitget/bars \
  --source-root binance=data/crypto/binance/bars \
  --output runs/charts/crypto_multi_source_viewer.html \
  --limit 5000 \
  --adjust none
```

默认启动动态 crypto viewer 的脚本：

```bash
./scripts/start_crypto_viewer.sh
```

脚本默认读取 `data/crypto`，优先使用 `uv run backtest`，没有 `uv` 时使用已安装的
`backtest` 命令；端口占用时会探测 `/api/manifest`，只有确认已有服务是 K-line
viewer 才直接打开。

日常运维说明文档：

```text
docs/market-data-operations.md
```

`--limit 5000` 是当前人工查看的折中：1m 等大数据级别仍可用 Position 看最近 5000 根内的早晚区间，HTML 文件也不会过大。需要完整历史时再用 `--limit 0`。

设计细节记录在：

```text
docs/superpowers/specs/2026-05-09-kline-cache-viewer-design.md
```

## 十大买讯能力

原始公式：

```text
docs/0504-十大买讯对应的量化公式.md
```

公式到代码说明：

```text
docs/ten-buy-signals-implementation.md
```

策略实现：

```text
strategies/ten_buy_signals.py
tests/strategies/test_ten_buy_signals.py
```

基础函数：

```text
generate_buy_signal_01
...
generate_buy_signal_10
```

固定持有退出包装函数：

```text
generate_buy_signal_01_hold_1
generate_buy_signal_01_hold_5
generate_buy_signal_01_hold_20
...
generate_buy_signal_10_hold_1
generate_buy_signal_10_hold_5
generate_buy_signal_10_hold_20
```

固定持有退出语义：

```text
买讯信号日 S
下一交易日 B 以 next_open 买入
持有 N 个交易日，B 算第 1 天
第 N 个持有交易日 H 生成 target_weight = 0
H 的下一交易日以 next_open 卖出
```

重叠入场会被忽略，以避免同一股票尚未退出时再次进入。

注意：

- 买讯 09 当前用样本池前两个股票近似“板块龙头同步走强”，还不是真实行业/概念板块联动；
- 买讯 10 在本轮 100 支、300 日样本中没有触发，不代表代码失败；
- 原始公式中的分钟级或事件数据条件，当前以日线技术替代实现。

## 已提交的十大买讯回测结果

配置：

```text
configs/ten_buy_signals/board_sample_20_each_300d/hold_1/*.yaml
configs/ten_buy_signals/board_sample_20_each_300d/hold_5/*.yaml
configs/ten_buy_signals/board_sample_20_each_300d/hold_20/*.yaml
```

结果：

```text
runs/ten_buy_signals/board_sample_20_each_300d/
```

核心文件：

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

已验证：

```text
30 个 case
30 个 report.html
0 个失败
100 支样本股
30000 行日 K
```

查看可视化结果：

```text
runs/ten_buy_signals/board_sample_20_each_300d/summary_dashboard.html
```

快速读取排名：

```bash
python - <<'PY'
import pandas as pd

summary = pd.read_csv("runs/ten_buy_signals/board_sample_20_each_300d/summary.csv")
cols = [
    "signal_id",
    "signal_slug",
    "holding_days",
    "entry_signal_rows",
    "trades",
    "total_return",
    "max_drawdown",
    "sharpe_ratio",
]
print(summary.sort_values("total_return", ascending=False)[cols].head(10).to_string(index=False))
PY
```

## 当前常用工作流

### 安装和测试

```bash
uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest
git diff --check
```

### 校验配置和信号

```bash
backtest validate config --config configs/demo.yaml
backtest validate signals --path signals/demo.csv --symbol 000001.SZ
```

### 获取股票池和行情

```bash
backtest data universe --output data/universe/a_share_all.csv
backtest data sample-pool --universe data/universe/a_share_all.csv --size 200 --seed 42 --output data/universe/sample_200_seed_42.txt
backtest data sync --config configs/demo.yaml --metadata data/metadata.sqlite --bars-root data/bars
```

### 用缓存行情直接跑 engine

在 CLI 缓存加载未打通前，批量回测建议用这种方式：

```python
from backtest.config.loader import load_config
from backtest.engine import BacktestEngine

config = load_config(config_path)
run_dir = BacktestEngine(config, config_path=config_path, bars_override=bars).run()
```

## 安全扩展地图

- 新增数据源：实现 `DataProvider.fetch_bars()`，不要把数据源逻辑写进 broker、metrics、reports。
- 新增加密历史行情：优先扩展 `backtest/data/ccxt_provider.py`，用 fake exchange 测试，不在单元测试访问真实网络。
- 新增批量数据任务：优先改 `backtest/data/jobs.py` 和 `backtest/cli/data.py`，继续复用 `DataSyncService`，不要复制 parquet 写入或 catalog coverage 逻辑。
- 新增缓存行为：改 `ParquetBarStore`、`DataCatalog` 或 `DataSyncService`。
- 新增信号格式：写新的 provider，但输出仍必须是 `SignalFrame`。
- 新增策略：放到 `strategies/`，通过 Python signal provider 接入。
- 新增 A 股回测撮合行为：改 `backtest/broker/`，补 broker 执行测试。
- 新增通用交易规划行为：改 `backtest/planning/`，补 `OrderIntent` 生成测试。
- 新增账户和仓位状态：改 `backtest/portfolio/`，保持 `account_id` 显式传递。
- 新增订单持久化或执行回报记录：改 `backtest/execution/`，保持 `(account_id, client_order_id)` 隔离。
- 新增真实 API 接入：先定义 `ExecutionAdapter` 边界，再接 `CCXT`；不要从策略、metrics 或 report 里直接调用 API。
- 新增指标：走 `MetricRegistry` 和 `MetricResult`。
- 新增 GUI/dashboard：消费 `manifest.json`、`metrics.json` 和 Parquet，不解析 HTML。
- 新增 K 线交互：优先改 `backtest/charts/kline_viewer.py`，补 `tests/charts/`。

## 未来 AI 必须遵守的边界

- 不要使用或宣传旧命令 `backtest backtest run`；当前命令形状是 `backtest run --config ...`。
- 不要承诺 `backtest run --config ...` 已能从缓存端到端跑通，除非先实现并验证 cached-bar loading。
- 保留验证层：配置模型、frame validators、symbol normalization、signal validation、report run ID validation 都是刻意设计。
- 读取和写入行情统一走 `ParquetBarStore`。
- 覆盖率和缓存库存统一走 `DataCatalog`，不要只从目录名推断。
- 策略代码保持在核心引擎外，通过 `FileSignalProvider` 或 `PythonSignalProvider` 接入。
- Broker 假设放在 broker/cost/slippage 层，不要塞进 signals 或 metrics。
- 指标不要去抓原始数据，也不要推断缓存路径，只消费回测结果上下文。
- dashboard 和 GUI 读取结构化产物，不要 scrape `report.html`。
- `source: akshare` 和日线是当前 MVP 约束，不是永久架构限制。
- `source: ccxt` 只代表历史行情源；不要把 `CCXTOHLCVProvider` 当成实盘交易适配器。
- crypto symbol 目前只支持简单现货 pair，如 `BTC/USDT`；不要悄悄把 `BTC/USDT:USDT` 合约 symbol 混进第一版。
- crypto 缓存路径必须使用 `safe_symbol_path()`，不要直接把 `/` 写进 partition path。
- crypto catalog source 必须带 exchange，例如 `ccxt:binance`，不要只写 `ccxt`。
- 批量拉取、重试、summary 产物和定时任务入口必须走 data job runner；不要把这些能力退回一次性脚本。
- Bitget historical OHLCV 必须使用最多 200 根每页的有效 limit；不要把默认 1000 直接传给 Bitget 历史分页。
- Bitget 大范围 `1m`、`5m` 补数容易触发 429；data job 可用 `page_delay_seconds`
  在每个 CCXT OHLCV 分页之间节流。
- 生成数据目录 `data/crypto/` 和运行产物目录 `runs/crypto_market_data/` 默认不提交。
- crypto `amount` 是 `close * volume` 估算值，不能当成交易所精确成交额。
- 当前 `BrokerEngine` 仍是 A 股撮合器；不要宣称 crypto 数据接入后就已经具备完整 crypto 回测。
- 不要混淆 `SignalFrame`、`TargetPortfolioFrame`、`OrderIntent`、`ExecutionReport`：
  `SignalFrame` 是旧回测信号，`TargetPortfolioFrame` 是目标组合，`OrderIntent` 是下单意图，`ExecutionReport` 是执行事实。
- 不要用 `OrderIntent` 更新仓位；只有 `ExecutionReport` 或回测撮合结果能驱动 `PortfolioState` 变化。
- 不要宣称项目已经具备真实 API 交易能力；当前 CCXT 能力只是历史行情，交易执行适配器还没做。
- 订单、执行回报、组合状态和 ledger 记录必须按账户隔离；第一版默认 `account_id="default"`，但接口不能写死只能单账户。
- 标识符归一化规则不能随意改：`instrument_id` 大写；`client_order_id`、`account_id`、`strategy_id` 只去首尾空格并保留原始大小写。
- 后续做多账户时，应扩展账户选择、账户级配置、跨账户汇总和执行路由；不要把多账户逻辑隐藏在全局变量里。
- 提交时避开 `.idea/`、`.DS_Store`、`__pycache__/` 和用户未要求的临时导出文件。
- 仓库可能有用户未提交改动；不要 revert、删除或覆盖不属于当前任务的文件。

## 当前已知限制

- `AkShareProvider` 只支持日线。
- `CCXTOHLCVProvider` 只支持 crypto spot 历史 OHLCV，不支持合约、WebSocket、订单簿或逐笔成交。
- `BrokerEngine` 只支持 `next_open`。
- CLI run 的缓存行情加载还没接好。
- 报告 HTML 总是写出，`report.html` 和 `report.charts` 开关还不完整。
- 十大买讯部分条件是日线近似，尚无分钟级或事件数据。
- 买讯 09 缺少真实板块成分数据。
- 本轮 30 case 是 100 支随机样本和 300 日窗口的探索结果，不是全市场最终结论。
- 通用交易架构还停在合同、状态、规划器和 ledger 第一阶段，没有真实交易 API 适配器。
- 尚未实现 `ExecutionAdapter`、`ExecutionRouter`、`RiskGate`、实盘 runner、守护进程或 live CLI。
- Market data sync jobs 当前是 CLI 触发和外部调度器友好入口，还没有项目内 daemon。
- 多账户目前是模型和 ledger 层预留口子，还没有账户调度、跨账户汇总、权限隔离或账户级风控。
- 当前已引入 `ccxt` 依赖用于历史行情，但没有任何交易所凭证管理或下单能力。
- crypto 回测撮合仍未完成；后续需要 fractional quantity、T+0、crypto fee model 和 `ExecutionReport -> PortfolioState` accounting。

## 当前交接验证命令

这组命令可以快速确认旧回测产物、通用交易合同和 crypto 历史行情合同仍可用：

```bash
uv pip install --python .venv/bin/python -e ".[dev]"

.venv/bin/python - <<'PY'
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

.venv/bin/python - <<'PY'
from datetime import UTC, datetime
from decimal import Decimal
from tempfile import TemporaryDirectory
from pathlib import Path

from backtest.core.orders import (
    ExecutionReport,
    ExecutionStatus,
    OrderIntent,
    OrderSide,
    OrderType,
)
from backtest.execution.ledger import SQLiteOrderLedger
from backtest.portfolio.state import PortfolioState

now = datetime(2026, 5, 8, tzinfo=UTC)
portfolio = PortfolioState.empty(updated_at=now, account_id="paper")
assert portfolio.account_id == "paper"

with TemporaryDirectory() as tmp:
    ledger = SQLiteOrderLedger(Path(tmp) / "orders.sqlite")
    for account_id in ["paper", "live"]:
        intent = OrderIntent(
            account_id=account_id,
            client_order_id="SameId",
            strategy_id="StrategyA",
            instrument_id="btc/usdt",
            side=OrderSide.BUY,
            quantity=Decimal("0.01"),
            order_type=OrderType.MARKET,
            created_at=now,
        )
        ledger.record_intent(intent)
    report = ExecutionReport(
        account_id="paper",
        client_order_id="SameId",
        instrument_id="BTC/USDT",
        status=ExecutionStatus.FILLED,
        order_quantity=Decimal("0.01"),
        filled_quantity=Decimal("0.01"),
        avg_fill_price=Decimal("64000"),
        reported_at=now,
    )
    ledger.record_report(report)
    assert ledger.get_order("paper", "SameId")["status"] == "filled"
    assert ledger.get_order("live", "SameId")["status"] == "created"

print("universal_contracts=true")
print("ledger_account_isolation=true")
PY

.venv/bin/python -m pytest \
  tests/core/test_symbols.py \
  tests/core/test_frames.py \
  tests/data/test_store.py \
  tests/data/test_ccxt_provider.py \
  tests/config/test_config_loader.py \
  tests/test_cli_commands.py \
  -q

git diff --check
.venv/bin/python -m pytest
```

最近一次完整验证结果：

```text
case_configs=30
summary_rows=30
reports=30
visualization=true
universal_contracts=true
ledger_account_isolation=true
crypto_market_data_targeted=59 passed, 2 warnings
159 passed, 2 warnings
```
