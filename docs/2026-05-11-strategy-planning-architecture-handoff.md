# 2026-05-11 Strategy Planning Architecture Handoff

这份文档总结 `feat/strategy-planning-architecture` 分支当前相对 `main`
需要关注的内容、已完成的能力、文档状态、运行方式和交接风险。它面向后续继续开发、
review 或合入前整理。

## Branch State

当前工作分支：

```text
feat/strategy-planning-architecture
```

当前分支 `HEAD`：

```text
c224156 Merge pull request #1 from Talonisherenow/feat/universal-trading-architecture
```

当前本地 `main`：

```text
fc7db17 Merge pull request #2 from Talonisherenow/feat/crypto-market-data
```

这意味着本分支的基础点落后于当前 `main`。直接看 `git diff main` 时，会看到
`main` 已经新增的 crypto market data、K-line service、data job 等文件在本分支里
表现为删除或回退。这不是本轮策略架构工作的意图；合入前需要先 merge 或 rebase
`main`，并重点处理 `backtest/charts/kline_*`、`backtest/cli/chart.py`、
`backtest/cli/data.py`、`backtest/data/*` 和相关 docs/tests 的重叠。

建议合入前先运行：

```bash
git status --short --branch
git log --oneline --decorate -n 8
git diff --name-status main
```

## Change Summary

本轮主要新增的是策略规划、回测 runtime、十大买讯迁移和动态可视化工作台。

### 1. Strategy Planning

新增策略阶段的清晰边界：

```text
SignalGenerator -> SignalScoreFrame
PortfolioAllocator -> TargetPortfolioFrame
StrategyPlanner -> StrategyPlan
```

核心位置：

```text
backtest/strategy/contracts.py
backtest/strategy/generator.py
backtest/strategy/planner.py
backtest/strategy/evaluation.py
backtest/portfolio/allocator.py
```

关键语义：

- `SignalScoreFrame` 表达策略判断、评分、排序和状态。
- `PortfolioAllocator` 把评分结果转换为目标仓位。
- `StrategyPlan` 同时保留信号评分和目标组合。
- 订单方向不在信号层决定，而是由目标仓位和当前仓位差额决定。

### 2. Backtest Runtime

新增外层回测 runtime：

```text
BacktestRunner -> ExecutionBackend -> BacktestRunResult
```

核心位置：

```text
backtest/runtime/backend.py
backtest/runtime/native.py
backtest/runtime/runner.py
backtest/runtime/results.py
backtest/runtime/adapters.py
```

已实现两个 backend：

- `NativeSimulationBackend`：新架构目标回测后端。
- `LegacyBrokerExecutionBackend`：包装 legacy `BrokerEngine`，用于迁移期 parity。

这层负责历史时间推进、策略计划收集、执行后端调用和结果聚合。它补齐了之前只讨论
`SignalGenerator`/`PortfolioAllocator` 时缺失的时间循环、执行和账户记账边界。

### 3. Ten Buy Signals

十大买讯仍保留原策略公式和固定持有期包装，但现在能通过新 runtime 的兼容路径进入
回测，并产出聚合结果：

```text
runs/ten_buy_signals/new_runtime_native_20260510/
```

主要结果文件：

```text
summary.csv
summary.json
orders.csv
trades.csv
equity_curve.csv
signals.csv
targets.csv
failures.json
```

当前第一版依旧是规则触发型信号：触发时给固定入场判断，退出由固定持有期包装补充。
强度、排序、复杂仓位管理可后续逐步改写为原生 `SignalGenerator`。

### 4. Dynamic Viewers And Workbench

新增策略结果和 K-line 的本地动态 viewer。正常使用时不需要在回测后生成一堆 HTML。

核心位置：

```text
backtest/charts/strategy_results_service.py
backtest/charts/strategy_results_server.py
backtest/charts/strategy_results_catalog.py
backtest/charts/strategy_account_viewer.py
backtest/charts/strategy_order_drilldown_viewer.py
backtest/charts/order_kline_viewer.py
backtest/charts/kline_service.py
backtest/charts/kline_server.py
backtest/charts/kline_viewer_template.html
backtest/charts/workbench_server.py
```

用户流程：

```text
backtest chart serve-workbench
  -> /
  -> /strategy-results
  -> /strategy-results/account?case_id=...
  -> /strategy-results/drilldown?case_id=...#symbol=...&order_id=...
  -> /kline
```

已完成的交互：

- Strategy Results 首页按策略展示多次回测结果。
- 结果行可整行点击进入账户级详情。
- Account Viewer 展示 holdings、equity/cash、return 和订单列表。
- Account Viewer 的订单行可进入 symbol drilldown。
- Drilldown 的订单行也可继续切换 symbol/order。
- rejected 订单保留在列表中，但不画在 K 线上。
- 买点标注在价格曲线下方，卖点标注在价格曲线上方。
- Holdings 图例支持分页、单击显隐、双击只看一个资产、再双击恢复。
- K-line viewer 保留原 bars window、overlap、older/newer/latest、jump 和 slider 交互。

## How To Run

推荐入口：

```bash
uv run backtest chart serve-workbench \
  --results-root runs/ten_buy_signals/new_runtime_native_20260510 \
  --a-share-bars-root data/bars \
  --bitget-bars-root data/crypto/bitget/bars \
  --host 127.0.0.1 \
  --port 8767
```

打开：

```text
http://127.0.0.1:8767/
```

单独启动 Strategy Results：

```bash
uv run backtest chart serve-results \
  --results-root runs/ten_buy_signals/new_runtime_native_20260510 \
  --bars-root data/bars \
  --host 127.0.0.1 \
  --port 8766
```

单独启动 K-line viewer：

```bash
uv run backtest chart serve \
  --a-share-bars-root data/bars \
  --bitget-bars-root data/crypto/bitget/bars \
  --host 127.0.0.1 \
  --port 8765
```

## Documentation Status

本轮文档已经覆盖这些层次：

```text
README.md
docs/architecture.md
docs/data-contracts.md
docs/signal-integration.md
docs/cli.md
docs/ai-handoff.md
docs/ten-buy-signals-implementation.md
docs/2026-05-05-ten-buy-signals-backtest-handoff.md
docs/2026-05-11-strategy-planning-architecture-handoff.md
docs/superpowers/specs/2026-05-10-strategy-planning-architecture-design.md
docs/superpowers/specs/2026-05-10-backtest-runtime-dual-backend-design.md
docs/superpowers/specs/2026-05-10-strategy-account-viewer-design.md
docs/superpowers/specs/2026-05-10-strategy-order-drilldown-design.md
docs/superpowers/specs/2026-05-10-strategy-results-catalog-design.md
docs/superpowers/plans/2026-05-10-strategy-planning-architecture.md
docs/superpowers/plans/2026-05-10-backtest-runtime-dual-backend.md
docs/superpowers/plans/2026-05-10-strategy-account-viewer.md
docs/superpowers/plans/2026-05-10-strategy-order-drilldown.md
docs/superpowers/plans/2026-05-10-strategy-results-catalog.md
docs/superpowers/plans/2026-05-11-chart-workbench-server.md
```

优先级说明：

- 运行和上手先看 `README.md`、`docs/cli.md`。
- 架构语义先看 `docs/architecture.md`、`docs/data-contracts.md`。
- 新会话交接先看 `docs/ai-handoff.md` 和本文档。
- 旧 dated plan/spec 是设计过程记录；若与当前代码冲突，以当前代码、测试、
  `README.md`、`docs/architecture.md`、`docs/data-contracts.md` 和本文档为准。

## Artifact Policy

建议提交：

```text
backtest/
tests/
docs/
README.md
uv.lock
```

通常不要提交，除非明确作为样例或验收截图：

```text
runs/charts/
runs/ten_buy_signals/
runs/crypto_market_data/
data/crypto/
.superpowers/
```

原因：这些目录主要是本地运行产物、缓存数据、截图或临时探索记录，容易让 review 噪声
盖过架构和代码变化。

## Known Follow-ups

- 合入前 merge/rebase 当前 `main`，处理 crypto market data 与 K-line service 重叠。
- 根据 merge 结果再次跑完整测试。
- 如果要把十大买讯完全原生化，下一步应把固定规则改成 `SignalGenerator`，再由
  `PortfolioAllocator` 统一决定仓位。
- `backtest run --config ...` 的直接缓存行情加载仍是 wiring point；当前完整回测通过
  程序化 `BacktestRunner` 路径验证。
- 当前没有真实交易 API、`RiskGate`、live `ExecutionAdapter` 或多账户调度。
