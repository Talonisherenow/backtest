# Strategy Planning Architecture Design

日期：2026-05-10
状态：已实现初版
分支：`feat/strategy-planning-architecture`
工作目录：`/Users/Tyrone.Shi/code-private/backtest`

## 1. 背景

当前项目仍处于早期阶段，但已经出现两套表达。本文档描述策略规划层的目标设计，并已在当前分支落地初版实现：

- 当前实际运行链路：`BacktestEngine -> SignalProvider -> BrokerEngine`
- 目标通用交易架构：`SignalGenerator -> PortfolioAllocator -> StrategyPlanner -> BacktestRunner/TradingRuntime -> ExecutionBackend/ExecutionAdapter`

这两套表达之间缺少一个清晰的过渡层。尤其是当前 `BrokerEngine` 同时承担了目标仓位转订单、A 股交易约束、模拟撮合、成交后账户更新等职责；而现有 `SignalProvider` 只能表达 `date, symbol, target_weight`，不能表达策略原始评分、排序、信号状态和实时 K 线内决策。

本设计把新架构作为后续主路径。老系统只保留为默认实现或兼容适配层：能低成本适配的模块包成 adapter；职责混杂或阻碍新边界的模块逐步替换。

## 2. 目标

第一阶段要建立清晰的新架构合同：

- 明确组件和数据产物的区别。
- 引入 `SignalGenerator` 作为信号生成组件。
- 引入 `SignalScoreFrame` 作为策略原始判断产物。
- 保留 `TargetPortfolioFrame` 作为目标仓位产物。
- 引入 `PortfolioAllocator`，负责把策略判断转成目标仓位。
- 引入 `StrategyPlanner`，负责编排 `SignalGenerator + PortfolioAllocator`，并输出完整策略计划。
- 保留并扩展 `OrderPlanner`，负责根据目标仓位和当前仓位生成订单意图。
- 引入 `SignalEvaluator`，在真实执行之前评估策略判断质量。
- 把现有 `FileSignalProvider` / `PythonSignalProvider` 包成 `LegacyStrategyPlanner` 默认实现。
- 保持现有 A 股回测可继续运行，迁移过程用老结果做回归参照。

## 3. 非目标

第一阶段不做：

- 真实券商、交易所、CCXT 下单适配器。
- 完整替换 `BrokerEngine` 主链路。
- 实盘调度、监控、告警和对账。
- Tick 级回测撮合。
- 多账户、多策略并发调度。
- 做空、杠杆、期货保证金、期权和永续合约账户模型。

这些能力需要建立在本设计定义的合同之上，后续分阶段补齐。

## 4. 组件与数据产物

### 4.1 组件

组件是可调用的行为单元：

```text
MarketDataProvider
UniverseProvider
SignalGenerator
PortfolioAllocator
StrategyPlanner
OrderPlanner
RiskGate
OrderLedger / OMS
ExecutionAdapter
PortfolioAccounting
SignalEvaluator
Metrics / Reports
```

### 4.2 数据产物

数据产物是组件之间传递的合同：

```text
HistoricalBars
RealtimeBarSnapshot
MarketSnapshot
CandidatePool
SignalScoreFrame
TargetPortfolioFrame
StrategyPlan
OrderIntent
ApprovedOrderIntent / RejectedOrderIntent
OrderRecord
ExecutionReport
PortfolioState
StrategyEvaluationResult
```

### 4.3 主交易链路

```text
[MarketDataProvider]
  -> HistoricalBars / RealtimeBarSnapshot / MarketSnapshot

[UniverseProvider]
  -> CandidatePool

[SignalGenerator]
  -> SignalScoreFrame

[PortfolioAllocator]
  -> TargetPortfolioFrame

[StrategyPlanner]
  -> StrategyPlan
       - signals: SignalScoreFrame
       - targets: TargetPortfolioFrame
       - metadata

[OrderPlanner]
  -> OrderIntent

[RiskGate]
  -> ApprovedOrderIntent / RejectedOrderIntent

[OrderLedger / OMS]
  -> OrderRecord

[ExecutionAdapter]
  -> ExecutionReport

[PortfolioAccounting]
  -> PortfolioState

[Metrics / Reports]
  -> metrics, parquet artifacts, html reports
```

### 4.4 策略评估侧链路

```text
[SignalGenerator]
  -> SignalScoreFrame

[FutureOutcomeBuilder]
  -> FutureOutcomeFrame

[SignalEvaluator]
  -> StrategyEvaluationResult
```

评估侧链路不调用 `PortfolioAllocator`、`StrategyPlanner`、`OrderPlanner` 或 `ExecutionAdapter`。它只评估策略判断和未来市场结果之间的关系，避免仓位分配、交易成本、撮合失败等后续噪音污染 SignalGenerator 的质量判断。

## 5. 核心合同

### 5.1 SignalGenerator

`SignalGenerator` 是信号生成组件。它不等于策略函数本身，也不等于输出表。它负责根据市场数据、候选标的、账户状态和策略参数生成标准化的信号评分。

建议接口：

```python
class SignalGenerator(Protocol):
    def generate(self, context: StrategyPlanningContext) -> pd.DataFrame:
        ...
```

第一阶段可以复用现有 `StrategyContext` 作为 legacy context，后续再扩展出 `StrategyPlanningContext`。

输出必须通过 `validate_signal_score_frame()` 验证为 `SignalScoreFrame`。`SignalGenerator` 不直接输出目标仓位，也不直接输出订单。

### 5.2 PortfolioAllocator

`PortfolioAllocator` 把 `SignalScoreFrame` 转换成 `TargetPortfolioFrame`。

建议接口：

```python
class PortfolioAllocator:
    def allocate(self, signals: pd.DataFrame) -> pd.DataFrame:
        ...
```

第一阶段支持：

- Top N 等权。
- score 加权。
- 最低 score 阈值。
- 单标的最大目标权重。
- 总目标仓位上限。
- `exit_preferred` 转成 `target_weight = 0`。
- `blocked` 不产生目标仓位。

### 5.3 StrategyPlanner

`StrategyPlanner` 是策略层编排组件。它把 `SignalGenerator` 和 `PortfolioAllocator` 组合起来，输出完整的本轮策略计划。

建议接口：

```python
class StrategyPlanner:
    def plan(self, context: StrategyPlanningContext) -> StrategyPlan:
        ...
```

默认新路径：

```text
SignalGenerator.generate(context) -> SignalScoreFrame
PortfolioAllocator.allocate(signals) -> TargetPortfolioFrame
StrategyPlanner.plan(context) -> StrategyPlan(signals, targets, metadata)
```

`StrategyPlanner` 不是信号模型，也不是组合分配模型。它只是策略阶段的编排层。

### 5.4 StrategyPlan

`StrategyPlan` 是 `StrategyPlanner` 的输出容器：

```text
plan_time
signals: SignalScoreFrame
targets: TargetPortfolioFrame
metadata: dict
```

默认路径要求：

- `signals` 用于解释和评估策略判断。
- `targets` 用于进入订单规划链路。
- `metadata` 记录 generator、allocator、legacy adapter 等来源信息。
- `StrategyPlan` 不包含 `OrderIntent`；订单由 `OrderPlanner` 生成。

### 5.5 SignalScoreFrame

`SignalScoreFrame` 表达策略对标的的原始判断，不表达最终订单动作。

必需列：

```text
signal_time
instrument_id
score
rank
signal_state
confidence
horizon
valid_until
reason
```

字段语义：

- `signal_time`：策略真正做出判断的时间。
- `instrument_id`：通用标的 ID。
- `score`：策略评分，越高代表越值得配置。
- `rank`：同一 `signal_time` 下的相对排序。
- `signal_state`：信号状态，不是订单方向。
- `confidence`：策略对判断的置信度，范围为 0 到 1。
- `horizon`：判断面向的持有或预测窗口，例如 `5m`、`1d`、`20bars`。
- `valid_until`：判断过期时间。
- `reason`：可读的策略原因或规则名称。

`signal_state` 第一阶段支持：

```text
long_preferred
neutral
exit_preferred
blocked
```

不使用 `buy`、`sell`、`hold` 作为 `signal_state`，因为真正的订单方向应由 `target_weight - current_weight` 在 `OrderPlanner` 中计算。

### 5.6 TargetPortfolioFrame

`TargetPortfolioFrame` 表达目标仓位，是后续交易链路的标准输入。

当前已有合同保持不变：

```text
timestamp
instrument_id
target_weight
```

第一阶段允许实现中携带诊断列，但后续模块只依赖上述三列。诊断列可以包括：

```text
source_score
source_rank
source_signal_state
source_reason
```

### 5.7 OrderPlanner

`OrderPlanner` 是目标仓位到订单意图的唯一入口。

输入：

```text
TargetPortfolioFrame
PortfolioState
prices / MarketSnapshot
TradingRule
created_at
```

输出：

```text
OrderIntent[]
```

订单方向在此处计算：

```text
target_weight > current_weight => buy
target_weight < current_weight => sell
target_weight == current_weight => no order
```

### 5.8 SignalEvaluator

`SignalEvaluator` 只评估 `SignalScoreFrame` 的判断质量。

输入：

```text
SignalScoreFrame
FutureOutcomeFrame
```

第一阶段结果指标：

```text
signal_count
matched_count
all_mean_forward_return
top_n_mean_forward_return
top_bottom_spread
rank_ic
```

## 6. 老系统整合策略

### 6.1 直接保留

这些模块继续作为基础设施：

```text
backtest.data.*
backtest.config.*
backtest.metrics.*
backtest.reports.*
backtest.core.instruments
backtest.core.targets
backtest.core.orders
backtest.portfolio.state
backtest.execution.ledger
backtest.planning.order_planner
```

### 6.2 包装适配

```text
FileSignalProvider / PythonSignalProvider
  -> LegacyStrategyPlanner

SignalFrame(date, symbol, target_weight)
  -> TargetPortfolioFrame(timestamp, instrument_id, target_weight)
```

`LegacyStrategyPlanner` 会直接输出 `StrategyPlan`。它会把旧 `SignalFrame` 转成 `TargetPortfolioFrame`，并从 `target_weight` 派生最小化的 `SignalScoreFrame`：

```text
score = target_weight
rank = same signal_time 内按 score 降序
signal_state = long_preferred if target_weight > 0 else exit_preferred
confidence = min(max(target_weight, 0), 1)
reason = legacy_target_weight
```

这不是理想信号解释，只是为了让旧策略能进入新合同。注意：legacy 适配层本身不是新的 `SignalGenerator + PortfolioAllocator` 实现，它是为了兼容旧策略已经混合了信号判断和目标仓位的事实。

### 6.3 拆分替换

`BrokerEngine` 不再作为新架构中心。它的职责拆分如下：

```text
BrokerEngine._build_intents
  -> OrderPlanner

现金不足、停牌、涨跌停、最小交易单位
  -> RiskGate + BacktestExecutionAdapter

模拟撮合和费用滑点
  -> BacktestExecutionAdapter

成交后账户更新
  -> PortfolioAccounting

BrokerResult
  -> reports/metrics 兼容输出
```

迁移期间保留 `BrokerEngine` 作为回归参照。新链路与老链路在 A 股 legacy 策略上的输出对齐后，再逐步降低 `BrokerEngine` 的中心地位。

## 7. 第一阶段文件结构

新增：

```text
backtest/strategy/__init__.py
backtest/strategy/contracts.py
backtest/strategy/generator.py
backtest/strategy/planner.py
backtest/strategy/evaluation.py
backtest/portfolio/allocator.py
tests/strategy/test_strategy_contracts.py
tests/strategy/test_strategy_planner.py
tests/strategy/test_signal_evaluator.py
tests/portfolio/test_allocator.py
```

修改：

```text
backtest/portfolio/__init__.py
docs/architecture.md
docs/data-contracts.md
```

暂不修改：

```text
backtest/engine.py
backtest/broker/engine.py
backtest/planning/order_planner.py
```

第一阶段先让新合同和默认适配实现存在，并用测试固定行为；不强行切换主回测入口。

## 8. 验收标准

- `SignalScoreFrame` 有明确验证器，能拒绝缺列、重复、非法 confidence、非法 signal_state。
- `StrategyPlan` 能验证并保存 signals、targets 和 metadata。
- `SignalGenerator` 的输出只包含 `SignalScoreFrame`，不包含目标仓位或订单。
- `StrategyPlanner` 能编排 `SignalGenerator + PortfolioAllocator` 并输出 `StrategyPlan`。
- `LegacyStrategyPlanner` 能包装现有 Python strategy，并输出 `StrategyPlan`。
- `PortfolioAllocator` 能把 signals 转成 `TargetPortfolioFrame`。
- `SignalEvaluator` 能在不执行交易的情况下评估策略判断质量。
- 文档中提到的第一阶段核心概念都能在代码中找到对应实现。
- 第一阶段不改变现有 `BacktestEngine` 和 `BrokerEngine` 行为。
- 新增测试和现有测试通过。

## 9. 设计自审

- 没有把组件和数据产物混写成同类节点。
- `buy/sell` 不在 `SignalScoreFrame` 中出现，避免与订单动作混淆。
- 旧策略能通过 `LegacyStrategyPlanner` 进入新合同。
- 第一阶段范围聚焦在信号生成、组合分配和策略计划，不包含完整执行链路重写。
- `BrokerEngine` 被保留为回归参照，不作为新架构中心继续扩展。
