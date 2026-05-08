# 通用标的回测与交易架构设计

日期：2026-05-07
状态：等待用户审阅
分支：`feat/universal-trading-architecture`
工作目录：`/Users/Tyrone.Shi/code-private/backtest`

## 1. 背景

当前项目是一套 A 股本地回测系统，已经具备数据源、信号加载、模拟撮合、指标和报告输出等基础能力。现有架构适合继续演进，但核心领域模型仍然以 A 股股票为中心：代码标准化只支持 A 股，配置里使用 `stock_pool`，执行模型内置 A 股手续费、T+1、100 股一手、涨跌停和停牌规则。

新的目标是把系统演进为通用标的物的回测与交易系统。A 股股票、港股股票、美股股票和加密货币在数据分析阶段都可以共享 OHLCV、信号计算、组合评价等模型，但在交易执行阶段必须按市场、交易所、券商或交易所 API 解耦。

## 2. 目标

本设计要支持：

- 同一套策略逻辑可以运行在回测和实盘交易环境。
- 策略不直接依赖券商 API、交易所 API 或回测撮合实现。
- 策略输出的目标仓位或订单意图可以被统一风控、记录和执行。
- 回测撮合和实盘 API 调用使用同一种订单意图合同。
- 仓位状态由成交事实更新，而不是由策略自行维护。
- A 股、港股、美股和加密货币的交易规则通过市场规则配置或适配器注入。

第一阶段目标是重构领域模型和执行链路，不接真实交易 API，也不改变现有 A 股回测结果的行为。

## 3. 非目标

第一阶段不做：

- QMT、Longbridge、IBKR、CCXT 等真实 API 适配器。
- 实盘定时调度、守护进程、监控告警。
- 多账户、多策略并发交易平台。
- 保证金、期货、期权、永续合约和复杂杠杆账户。
- Tick 级撮合和完整订单簿撮合。
- GUI 或 Web 控制台。

这些能力要建立在统一订单、仓位、执行回报和台账模型之上。

## 4. 核心判断

回测引擎和实盘交易引擎不应完全相同。它们应共享：

- `Instrument`
- `MarketDataProvider`
- `StrategyRunner`
- `TargetPortfolio`
- `OrderPlanner`
- `OrderIntent`
- `RiskGate`
- `OrderLedger`
- `ExecutionReport`
- `PortfolioState`

它们不共享：

- 成交来源。回测由模拟撮合生成成交，实盘由券商或交易所 API 返回成交。
- 时间驱动方式。回测按历史数据推进，实盘按行情、定时任务或事件推进。
- 失败模式。回测失败主要是数据或规则问题，实盘还会有网络、限频、认证、拒单、部分成交和对账问题。

## 5. 目标架构

```text
MarketDataProvider
  -> StrategyRunner
  -> TargetPortfolio / OrderIntent
  -> RiskGate
  -> OrderLedger
  -> ExecutionAdapter
      - BacktestSimulationAdapter
      - LiveBrokerAdapter
  -> ExecutionReport
  -> PortfolioAccounting
  -> PortfolioState
```

### 回测流程

```text
HistoricalMarketDataProvider
  -> StrategyRunner
  -> TargetPortfolio
  -> OrderPlanner
  -> RiskGate
  -> OrderLedger
  -> BacktestSimulationAdapter
  -> ExecutionReport
  -> PortfolioAccounting
  -> Reports
```

### 实盘流程

```text
RealtimeMarketDataProvider
  -> StrategyRunner
  -> TargetPortfolio 或 OrderIntent
  -> OrderPlanner
  -> RiskGate
  -> OrderLedger
  -> LiveBrokerAdapter
  -> ExecutionReport
  -> PortfolioAccounting
  -> Reconciliation
```

## 6. 核心概念

### 6.1 Instrument

`Instrument` 是系统内统一标的定义，替代单纯的 `symbol` 概念。

字段：

```text
instrument_id
market
exchange
asset_class
quote_currency
lot_size
tick_size
min_order_quantity
min_order_notional
trading_timezone
```

示例：

```text
000001.SZ             A_SHARE      SZSE      CNY
00700.HK              HK_STOCK     HKEX      HKD
AAPL.US               US_STOCK     NASDAQ    USD
BTC-USDT.BINANCE      CRYPTO_SPOT  BINANCE   USDT
```

`normalize_symbol()` 不再适合作为全局入口。它应逐步降级为 A 股兼容函数。未来每个市场适配器可以有自己的 symbol normalizer。

### 6.2 Universe

`Universe` 是策略可交易或可研究的标的集合，替代 `stock_pool`。

第一阶段保留 `stock_pool` 兼容，但内部应能转换为 `Universe`。旧配置继续能跑，新配置可以显式声明市场和标的类型。

### 6.3 MarketDataProvider

市场数据分三类：

- 历史行情：给回测使用。
- 实时行情：给实盘策略和风控使用。
- 交易规则：给订单规划、风控和执行适配器使用。

现有 `DataProvider.fetch_bars()` 可以继续作为历史行情接口。后续应补充 `MarketSnapshot` 和 `TradingRule` 的读取接口。

### 6.4 StrategyRunner

`StrategyRunner` 是策略运行的统一入口。策略不应该知道自己运行在回测还是实盘。

输入：

```text
MarketSnapshot
PortfolioState
StrategyState
params
```

输出：

```text
TargetPortfolio 或 OrderIntent
```

当前 `PythonSignalProvider` 可以看作早期形态。它只接收历史 bars，输出 `target_weight` 信号。第一阶段应保持兼容，把旧 `SignalFrame` 包装为新的 `TargetPortfolioFrame`。

### 6.5 TargetPortfolio

`TargetPortfolio` 表示策略想要的组合目标。

示例：

```text
00700.HK target_weight=0.20
BTC-USDT.BINANCE target_weight=0.10
```

它不关心交易单位、现金是否足够、是否交易时间、如何下单。这些由后续模块处理。

### 6.6 OrderPlanner

`OrderPlanner` 把目标仓位转换成订单意图。

输入：

```text
TargetPortfolio
PortfolioState
MarketSnapshot
TradingRule
```

输出：

```text
OrderIntent[]
```

它处理当前仓位、目标差额、现金、价格、lot size、tick size、最小下单数量和最小名义金额。A 股 100 股一手、港股每只股票不同手数、加密货币小数数量、美股碎股支持，都属于这个层面的规则。

### 6.7 OrderIntent

`OrderIntent` 是策略或订单规划器希望提交的标准订单命令。

字段：

```text
account_id
client_order_id
strategy_id
instrument_id
side
quantity
order_type
limit_price
time_in_force
created_at
reason
```

`OrderIntent` 不等于成交，也不等于券商订单。它只是系统内部准备提交的订单请求。

### 6.8 RiskGate

`RiskGate` 是资金安全防火墙。任何订单意图提交执行前都必须通过风控。

第一阶段规则：

- 单标的最大目标权重。
- 单笔最大名义金额。
- 买入订单不能超过可用现金。
- 数量必须满足交易规则。
- `dry_run` 模式下禁止真实提交。

后续可扩展：

- 日内最大交易次数。
- 黑名单和白名单。
- 价格偏离限制。
- 最大回撤后停止交易。
- 交易时间检查。

### 6.9 OrderLedger

`OrderLedger` 是订单事实记录，不是报告层。它记录订单从意图、风控、提交、成交、撤单、失败到对账的完整生命周期。

字段：

```text
client_order_id
strategy_id
instrument_id
side
quantity
order_type
limit_price
status
submitted_at
broker_order_id
filled_quantity
avg_fill_price
error
raw_response
```

有了台账，交易系统可以恢复、重试、对账，也可以把实盘和回测统一到同一类订单流水。

### 6.10 ExecutionAdapter

`ExecutionAdapter` 隔离具体执行来源。

统一接口：

```text
submit_order(OrderIntent) -> OrderSubmission
cancel_order(client_order_id) -> CancelResult
fetch_open_orders() -> list[OrderState]
fetch_positions() -> PortfolioState
stream_reports() -> Iterator[ExecutionReport]
```

适配器类型：

```text
BacktestSimulationAdapter
DryRunExecutionAdapter
QMTAdapter
LongbridgeAdapter
IBKRAdapter
CCXTAdapter
```

第一阶段只实现 `BacktestSimulationAdapter` 或保留现有回测撮合并逐步包裹成适配器。

### 6.11 ExecutionReport

`ExecutionReport` 表示执行层返回的事实。

状态：

```text
accepted
partially_filled
filled
canceled
rejected
expired
failed
```

字段：

```text
account_id
client_order_id
instrument_id
status
order_quantity
filled_quantity
avg_fill_price
reported_at
broker_order_id
error
raw_response
```

回测中由模拟撮合生成，实盘中由券商或交易所 API 返回。`ExecutionReport` 才是更新仓位的依据。

### 6.12 PortfolioState

`PortfolioState` 是账户和组合状态。

字段：

```text
account_id
cash_by_currency
positions
pending_orders
updated_at
```

`Position` 字段：

```text
instrument_id
quantity
available_quantity
avg_cost
market_price
currency
```

数量使用 `Decimal`，不再固定为 `int shares`。这可以支持加密货币小数数量、美股碎股和港股/美股/A 股不同交易单位。

### 6.13 PortfolioAccounting

`PortfolioAccounting` 根据成交事实更新仓位。

```text
ExecutionReport + previous PortfolioState
  -> next PortfolioState
```

策略不能直接修改真实仓位。仓位来自成交事实和对账结果。

## 7. 现有模块迁移关系

### `backtest/core`

新增通用领域模型：

```text
instruments.py
orders.py
portfolio.py 或 backtest/portfolio/state.py
market.py
```

现有 `symbols.py` 保留 A 股兼容能力，但不能继续作为所有市场的统一代码标准化入口。

### `backtest/config`

新增 `UniverseConfig`，逐步替代 `StockPoolConfig`。第一阶段保留旧配置，加载时把 `stock_pool.symbols` 转换为默认 A 股 `Instrument`。

### `backtest/data`

保留现有历史行情接口。后续可以扩展：

```text
MarketSnapshotProvider
TradingRuleProvider
```

### `backtest/signals`

保留 `FileSignalProvider` 和 `PythonSignalProvider`。第一阶段新增适配层，把旧 `SignalFrame` 转成 `TargetPortfolioFrame`。

### `backtest/broker`

现有 `BrokerEngine` 应逐步拆分：

```text
OrderPlanner
BacktestSimulationAdapter
PortfolioAccounting
```

第一阶段先新增独立 `OrderPlanner`，用测试证明它能表达目标仓位到订单意图的转换。`BrokerEngine` 的内部迁移应在回归测试保护下推进；如果直接替换会改变现有 A 股回测语义，应先保持 `BrokerEngine` 不变，只通过旧结果表继续输出 `orders/trades/positions/equity_curve`。

### `backtest/reports`

报告层继续消费结果，不直接参与交易执行。未来可以同时读取 `OrderLedger` 和 `ExecutionReport` 做更丰富的交易诊断。

## 8. 第一阶段验收标准

第一阶段完成后应满足：

- 旧 A 股回测配置和测试继续通过。
- 系统新增 `Instrument`、`TradingRule`、`TargetPortfolio`、`OrderIntent`、`PortfolioState`、`ExecutionReport` 等通用模型。
- 旧 `SignalFrame` 可以转换为新的 `TargetPortfolioFrame`。
- `OrderPlanner` 可以独立把目标仓位转换成订单意图。
- A 股 100 股一手、T+1 可卖、手续费等规则仍能表达。
- 当前回测结果表不因架构调整而改变语义。
- 真实 API 适配器仍未接入，但后续可以通过 `ExecutionAdapter` 添加。

## 9. 关键边界

三组关系必须保持清楚：

```text
TargetPortfolio != OrderIntent
OrderIntent != ExecutionReport
ExecutionReport 才能更新 PortfolioState
```

策略负责表达意图，订单规划负责翻译意图，风控负责拦截风险，执行适配器负责对外通信，成交回报负责更新账户。

## 10. 当前假设

- 第一阶段以 A 股现有回测为兼容基准。
- 通用模型使用 `Decimal` 表达数量和金额相关字段。
- 新模块先在本地 Python package 内实现，不引入服务端数据库或外部依赖。
- `OrderLedger` 第一阶段实现简单 SQLite 版本，用于记录订单意图和执行回报。
- 第一阶段按单账户实现，模型预留 `account_id`，默认值为 `default`。
- 第一个真实 API 适配器优先接 `CCXT`。
- 实盘运行入口优先支持 CLI 手动触发，同时保留后续守护进程循环复用的引擎边界。
- 任何订单、成交、仓位、台账记录都不得脱离 `account_id` 存在；第一阶段默认 `account_id='default'`。

## 11. 多账户说明

多账户指同一个系统同时管理多个交易账户或资金单元。例如：

- 一个策略同时跑在模拟账户和实盘账户。
- 同一个人有 A 股、港股、加密货币多个券商或交易所账户。
- 同一市场里有保守账户和激进账户，仓位、风控、订单流水需要隔离。
- 后续多策略平台需要按账户统计现金、持仓、订单和成交。

多账户的核心功能是让 `PortfolioState`、`OrderIntent`、`ExecutionReport` 和 `OrderLedger` 都带 `account_id`，避免不同账户的现金、仓位和订单混在一起。第一阶段不实现多账户调度和多账户聚合，只保留 `account_id='default'` 字段，后续扩展时不用重写订单和仓位合同。

第一阶段需要预留的口子：

- `OrderIntent.account_id`：订单意图属于哪个账户。
- `ExecutionReport.account_id`：成交回报来自哪个账户。
- `PortfolioState.account_id`：仓位和现金属于哪个账户。
- `OrderLedger` 主键使用 `(account_id, client_order_id)`。
- `OrderPlanner` 从 `PortfolioState.account_id` 继承账户标识，生成同账户订单。
- 后续 `ExecutionRouter` 可以根据 `account_id` 选择对应的 `ExecutionAdapter`。
- 后续 `RiskGate` 可以按 `account_id` 做账户级风控。

后续多账户配置形态可以是：

```yaml
accounts:
  - id: default
    mode: paper
    adapter: dry_run

  - id: binance_spot
    mode: live
    adapter: ccxt
    exchange: binance
```

第一阶段不实现完整 `accounts` 配置解析，但所有核心交易合同按上述形态预留。

## 12. 后续阶段方向

- Phase 2：实现 `DryRunExecutionAdapter` 和 `CCXTAdapter`。
- Phase 3：实现 CLI 实盘单次运行入口。
- Phase 4：实现守护进程循环运行、对账和恢复能力。
- Phase 5：评估是否需要多账户调度、多策略隔离和跨账户报告。
