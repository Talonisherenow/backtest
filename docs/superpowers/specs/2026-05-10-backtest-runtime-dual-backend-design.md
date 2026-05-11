# Backtest Runtime Dual Backend Design

日期：2026-05-10
状态：已实现初版
分支：`feat/strategy-planning-architecture`
工作目录：`/Users/Tyrone.Shi/code-private/backtest`

## 1. 背景

当前新架构已经补充了策略阶段。本文档描述回测 runtime 层的目标设计，并已在当前分支落地初版实现：

```text
SignalGenerator -> SignalScoreFrame
PortfolioAllocator -> TargetPortfolioFrame
StrategyPlanner -> StrategyPlan
```

但这只能描述单次策略决策。完整回测还需要一个外层 runtime，把历史时间推进、策略计划、目标仓位、执行成交、账户记账和结果记录串成连续过程。当前项目里的这部分能力主要藏在旧的 `BacktestEngine + BrokerEngine` 中，其中 `BrokerEngine` 同时承担了目标仓位转交易、交易约束、撮合、账户更新和权益曲线记录。

这份设计补齐新架构中的回测 runtime，同时保留旧 `BrokerEngine` 作为迁移参照。目标不是先做一个临时兼容层就结束，而是让兼容后端和原生后端共用同一套 runner、合同和测试，从第一天就能无缝迁移。

## 2. 目标

- 引入 `BacktestRunner` 作为新架构的回测外层执行器。
- 引入统一的 `ExecutionBackend` 合同。
- 第一阶段实现 `LegacyBrokerExecutionBackend`，复用现有 `BrokerEngine` 跑通完整回测。
- 紧接着实现 `NativeSimulationBackend`，走新架构拆分后的订单规划、模拟执行和账户记账。
- 两个 backend 输出同一个 `BacktestExecutionResult`。
- 建立 parity tests，用同一组 bars、targets 和 execution config 对照 legacy backend 与 native backend 的结果。
- 为十大买讯接入新架构准备默认路径：规则型 `SignalGenerator` 产生信号，默认 `PortfolioAllocator` 产生目标仓位，`BacktestRunner` 负责跑完整回测。

## 3. 非目标

本阶段不做：

- 真实券商、交易所或 CCXT 适配。
- Tick 级撮合。
- 多账户、多策略并发运行。
- 做空、杠杆、期货保证金、期权和永续合约账户模型。
- 十大买讯规则本体重写。
- 实盘调度、监控、告警和对账。

## 4. 新增组件

### 4.1 BacktestRunner

`BacktestRunner` 是新架构的回测外层执行器。它负责：

```text
HistoricalBars
  -> planning loop
  -> StrategyPlanner.plan(...)
  -> collect StrategyPlan[]
  -> collect TargetPortfolioFrame sequence
  -> ExecutionBackend.execute(...)
  -> BacktestRunResult
```

第一版支持两种规划模式：

```text
walk_forward
batch
```

`walk_forward` 是新策略默认模式：runner 按 `bars.date` 推进，每个 `decision_time` 只给策略看到截至当前时间的 K 线，并只收集当前时间的新目标仓位。

`batch` 是兼容模式：runner 对完整历史调用一次 `StrategyPlanner`，直接得到完整目标仓位序列。这个模式用于旧策略结果复现和 parity 测试，不作为新策略默认写法。

### 4.2 ExecutionBackend

`ExecutionBackend` 是目标仓位序列到执行结果的统一接口：

```python
class ExecutionBackend(Protocol):
    name: str

    def execute(
        self,
        bars: pd.DataFrame,
        targets: pd.DataFrame,
        config: ExecutionConfig,
    ) -> BacktestExecutionResult:
        ...
```

`BacktestRunner` 只依赖这个接口。后续从 legacy backend 切换到 native backend，不应该修改 runner 或策略代码。

### 4.3 LegacyBrokerExecutionBackend

`LegacyBrokerExecutionBackend` 是第一阶段兼容后端：

```text
TargetPortfolioFrame
  -> legacy SignalFrame(date, symbol, target_weight)
  -> BrokerEngine.run(bars, signals)
  -> BacktestExecutionResult
```

它的作用是让新架构的 `StrategyPlan.targets` 立刻可以进入当前成熟的 A 股回测执行内核。它不新增交易语义，只做格式适配和结果包装。

因为当前 `BrokerEngine` 和 legacy `SignalFrame` 验证器仍以 A 股符号和 A 股交易规则为中心，`LegacyBrokerExecutionBackend` 第一版也只承诺 A 股回测兼容。加密货币、期货和其他市场应优先走后续的 native backend 扩展。

### 4.4 NativeSimulationBackend

`NativeSimulationBackend` 是原生回测后端：

```text
TargetPortfolioFrame
  -> target scheduling(next_open)
  -> OrderPlanner
  -> ExecutionSimulator
  -> PortfolioAccounting
  -> BacktestExecutionResult
```

第一版 native backend 必须对齐当前 `BrokerEngine` 的 A 股语义：

- `execution.timing = next_open`
- 同一执行日卖出先于买入
- 同一标的同一执行日保留最后一个目标仓位
- 100 股一手或按 `TradingRule.lot_size` 取整
- 手续费、最低佣金、印花税、过户费
- 固定比例滑点
- 涨停拒绝买入、跌停拒绝卖出、停牌拒绝交易
- 现金不足时买入数量下调或拒绝
- T+1 可卖数量
- 每日收盘后记录权益曲线

### 4.5 BacktestExecutionResult

两个 backend 统一输出：

```text
equity_curve
positions
orders
trades
metadata
```

其中前四个 DataFrame 第一版沿用当前 `BrokerResult` 的列，保证 metrics 和 reports 可以复用。

### 4.6 BacktestRunResult

`BacktestRunner.run()` 输出：

```text
plans: list[StrategyPlan]
signals: SignalScoreFrame
targets: TargetPortfolioFrame
execution: BacktestExecutionResult
metadata: dict
```

`signals` 和 `targets` 是所有计划结果的合并表，用于调试、解释和后续报告。

## 5. 运行链路

### 5.1 兼容后端链路

```text
BacktestRunner
  -> StrategyPlanner
  -> StrategyPlan.targets
  -> LegacyBrokerExecutionBackend
  -> BrokerEngine
  -> BacktestRunResult
```

这条链路用于快速把新策略架构接入当前回测能力。

### 5.2 原生后端链路

```text
BacktestRunner
  -> StrategyPlanner
  -> StrategyPlan.targets
  -> NativeSimulationBackend
       -> OrderPlanner
       -> ExecutionSimulator
       -> PortfolioAccounting
  -> BacktestRunResult
```

这条链路是目标架构。它逐步取代 `BrokerEngine` 在新架构中的中心地位。

### 5.3 十大买讯接入路径

十大买讯原始文档主要提供规则型买入触发，不提供完整仓位管理。新架构接入时应按以下方式补齐：

```text
TenBuySignalGenerator
  -> SignalScoreFrame(long_preferred / exit_preferred)

PortfolioAllocator(default top_n/equal/max_weight)
  -> TargetPortfolioFrame

BacktestRunner
  -> LegacyBrokerExecutionBackend or NativeSimulationBackend
  -> BacktestRunResult
```

默认组合参数建议：

```text
top_n = 5
weighting = equal
total_target_weight = 1.0
max_weight_per_instrument = 0.2
```

退出策略不是十大买讯原文的完整组成部分。第一版可通过外接 `ExitPolicy` 或固定持有期 generator 补齐，后续再加入止损和均线跌破等规则。

## 6. 迁移原则

### 6.1 同接口

`BacktestRunner` 永远只依赖 `ExecutionBackend`。legacy 和 native 后端必须可替换：

```python
runner = BacktestRunner(planner=planner, backend=LegacyBrokerExecutionBackend())
runner = BacktestRunner(planner=planner, backend=NativeSimulationBackend())
```

### 6.2 同结果

两个后端都返回 `BacktestExecutionResult`。不允许 runner 消费 `BrokerResult` 或 native 私有结果。

### 6.3 同测试

所有 runtime 端到端测试都应能参数化 backend：

```python
@pytest.mark.parametrize("backend_factory", [
    LegacyBrokerExecutionBackend,
    NativeSimulationBackend,
])
def test_runner_executes_target_portfolio(backend_factory):
    ...
```

### 6.4 parity tests

保留专门的对照测试：

```text
same bars
same targets
same execution config
LegacyBrokerExecutionBackend.execute(...)
NativeSimulationBackend.execute(...)
compare orders/trades/equity/positions
```

只要 `BrokerEngine` 仍然存在，它就是 native backend 的回归参照。

## 7. 文件结构

新增：

```text
backtest/runtime/__init__.py
backtest/runtime/results.py
backtest/runtime/adapters.py
backtest/runtime/backend.py
backtest/runtime/runner.py
backtest/runtime/native.py
tests/runtime/test_runtime_adapters.py
tests/runtime/test_legacy_backend.py
tests/runtime/test_native_backend_parity.py
tests/runtime/test_backtest_runner.py
```

后续 native 拆分变复杂时，可以再把 `native.py` 拆成：

```text
backtest/runtime/execution.py
backtest/runtime/accounting.py
```

第一版先保持文件数量可控。

## 8. 验收标准

- `BacktestRunner` 能通过 `StrategyPlanner` 产生 `StrategyPlan`、合并 signals 和 targets。
- `LegacyBrokerExecutionBackend` 能消费 `TargetPortfolioFrame` 并复用 `BrokerEngine` 输出完整回测结果。
- `NativeSimulationBackend` 能在核心 A 股场景上与 legacy backend 对齐。
- parity tests 覆盖买入、卖出、同日 rebalance、现金不足、停牌、涨跌停和 T+1。
- runtime 端到端测试能通过参数化 backend 跑同一用例。
- 十大买讯后续只需要提供 `SignalGenerator` 和默认 allocator，就能进入 `BacktestRunner`。

## 9. 设计自审

- 没有把 `BacktestRunner` 放进 `StrategyPlanner`；策略阶段和回测 runtime 边界清楚。
- legacy backend 是迁移后端，不是新架构最终执行中心。
- native backend 从一开始就有 parity tests，避免兼容层变成永久债务。
- `PortfolioAllocator` 仍然只输出目标仓位；复利、成交和账户状态由 runtime/backend 处理。
- 十大买讯缺失的仓位和退出能力通过默认 allocator 和外接 exit policy 补齐，不写回买讯规则本体。
