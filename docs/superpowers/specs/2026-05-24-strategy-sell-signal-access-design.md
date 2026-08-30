# Strategy Sell Signal Access Design

Date: 2026-05-24
Branch: `strategy-sell-signal-access`
Status: approved for implementation planning

## Goal

接入「十大卖讯」到现有回测系统，同时支持两种使用方式：

1. 独立卖出策略：每个卖讯函数在触发日输出 `target_weight=0.0`，用于已有持仓或组合清仓场景。
2. 买入策略叠加卖出退出：现有十大买入策略仍负责入场；持仓期间若任一卖讯先触发，则提前清仓，否则按固定持有期退出。

实现应沿用现有十大买入策略的接入方式：Python 策略函数通过 YAML `signals.path` + `signals.function` 接入，输出 legacy signal frame：

```text
date,symbol,target_weight
```

## Existing Context

现有十大买入策略集中在 `strategies/ten_buy_signals.py`：

- `generate_buy_signal_01..10(context)` 生成入场信号。
- `generate_buy_signal_XX_hold_1/5/20(context)` 生成入场信号，并在固定持有期后输出 `target_weight=0.0` 退出。
- YAML 配置位于 `configs/ten_buy_signals/`，通过 `signals.type: python` 指向策略函数。
- `BrokerEngine` 只支持 `next_open`，因此策略在信号日输出 `target_weight=0.0` 后，实际卖出在下一交易日开盘执行。

这次不修改 broker 主链路，不引入新的信号格式，不改变现有买入策略语义。

## Architecture

### Strategy Modules

新增 `strategies/ten_sell_signals.py`，提供：

- `generate_sell_signal_01(context)` 到 `generate_sell_signal_10(context)`。
- `_SELL_SIGNAL_GENERATORS` 字典，便于组合退出策略复用。
- `generate_sell_signal_any(context)`，在任一卖讯触发时输出清仓信号。
- `make_buy_with_sell_exit_generator(entry_generator, holding_days, exit_generator)` 风格的内部工具，用于生成买入叠加卖出退出策略。
- `generate_buy_signal_XX_hold_N_or_sell_signal_exit(context)` 形式的组合函数，覆盖 `XX=01..10`、`N in {1,5,20}`。

若买入和卖出策略共享 helper 过多，可以新增 `strategies/common_signals.py`，将 `_prepare_daily_bars`、`_weekly_bars`、`_ma`、`_shift` 等无业务含义的工具迁出。这个抽取只做复用，不改变现有买入策略行为。

### Configs

新增独立卖讯配置：

```text
configs/ten_sell_signals/sell_signal_01_extreme_volume_no_follow.yaml
...
configs/ten_sell_signals/sell_signal_10_break_high_voltage_line.yaml
```

每个配置使用：

```yaml
signals:
  type: python
  path: ../../strategies/ten_sell_signals.py
  function: generate_sell_signal_XX
```

新增组合退出配置目录：

```text
configs/ten_buy_sell_signals/hold_1/
configs/ten_buy_sell_signals/hold_5/
configs/ten_buy_sell_signals/hold_20/
```

每个配置以对应买入策略命名，并指向 `ten_sell_signals.py` 中的组合函数，例如：

```yaml
signals:
  type: python
  path: ../../../strategies/ten_sell_signals.py
  function: generate_buy_signal_01_hold_5_or_sell_signal_exit
```

## Sell Signal Definitions

所有卖讯输出列为 `date`, `symbol`, `target_weight`。触发时 `target_weight=0.0`。

### 卖讯一：天量之后无量跟进

使用文档中的滚动窗口简化判断：

- `prior_extreme_volume = max(volume[t-20:t-10])`
- `recent_max_volume = max(volume[t-10:t])`
- 当 `recent_max_volume < prior_extreme_volume` 时触发。

需要至少 21 根日线数据。

### 卖讯二：龙头股率先走弱

沿用买讯九的本地约定：`context.stock_pool[:2]` 是同板块两只龙头。

单只龙头走弱条件：

- 连续 3 日收盘价下跌；或
- 最近 5 个交易日内 4 个相邻比较为下跌。

当两只龙头在同一交易日均走弱时，对这两只龙头输出清仓信号。

### 卖讯三：连续两日高开低走

触发条件：

- `open[t] > close[t-1]`
- `open[t-1] > close[t-2]`
- `close[t]` 和 `close[t-1]` 均位于当日振幅最低 10% 区域。

当 `high == low` 时不触发低位收盘判断，避免除零。

### 卖讯四：涨超 30% 后 10 日均线翻下

触发条件：

- 当前收盘价相对过去 21 个交易日最低收盘价涨幅 `>= 30%`。
- 当日 `MA10(close)` 小于前一日 `MA10(close)`。

### 卖讯五：单日暴量收低或长上影线

触发条件：

- `volume[t] >= 2 * MA5(volume)[t]`
- 同时满足以下任一：
  - 收盘价位于当日振幅最低 10% 区域；
  - 上影线长度 / 实体长度 `>= 2`，且实体长度大于 0。

### 卖讯六：周线天量后股价走弱

沿用现有 `_weekly_bars()` 从日线聚合周线。

触发条件：

- 最近完成周的周成交量为过去 20 周最大。
- 周线天量周后的两个日线交易日连续下跌，或两日累计跌幅超过 3%。

信号确认在第二个交易日。

### 卖讯七：一周震荡收于最低价

沿用日线聚合周线。

触发条件：

- 周收盘价位于周内最低价。
- 周振幅 `(weekly_high - weekly_low) / weekly_low >= 5%`。

信号日期使用该周最后一个交易日。

### 卖讯八：股价快速回落超 20%

触发条件：

- `peak = max(close[t-19:t])`
- `(peak - close[t]) / peak >= 20%`

需要至少 20 根日线数据。

### 卖讯九：双峰形态且跌破颈线

使用文档中的简化 60 日窗口：

- `H1 = max(close[t-60:t-30])`
- `H2 = max(close[t-29:t])`
- `abs(H1 - H2) / H1 <= 3%`
- 两顶之间存在至少 10% 回调。
- 当前收盘价跌破两顶之间颈线低点。

为避免把全窗口最低点误作当前跌破点，颈线只取两个高点日期之间的最低收盘价。

### 卖讯十：跌破“高压电线”

定义：

- `gravity = (MA30(close) + MA72(close)) / 2`
- `high_voltage = 1.2 * gravity`

触发条件：

- `high_voltage` 最近 5 日走平或下行：`high_voltage[t] - high_voltage[t-5] <= 0`
- 连续两日收盘价低于各自的 `high_voltage`。

## Buy With Sell Exit Semantics

组合策略需要在同一个 symbol 的买入执行后追踪持仓窗口：

1. 对候选买入信号按 `date, symbol` 排序。
2. 买入信号日的实际执行日为下一交易日。
3. 固定持有期退出信号日为 `entry_execution_index + holding_days - 1`。
4. 卖讯退出只在入场执行日之后、固定退出信号日之前或当天生效。
5. 若多个卖讯触发，取最早交易日输出 `target_weight=0.0`。
6. 若没有卖讯触发，则保留固定持有期退出。
7. 若当前 symbol 已有未结束持仓窗口，跳过新的买入候选，沿用现有十大买入策略的非重叠行为。

组合策略的入场权重继续使用现有 `_with_target_weights` 分配逻辑。

## Testing Strategy

测试采用 TDD：

- 新增 `tests/strategies/test_ten_sell_signals.py`。
- 为每个 `generate_sell_signal_XX` 写一个最小触发样例，先验证失败，再实现。
- 写配置测试，确保 10 个独立卖讯 YAML 均指向存在的函数。
- 写组合退出测试，构造一个买入信号与较晚固定退出，同时让卖讯提前触发，断言退出日为卖讯日。
- 写组合配置测试，确保 `hold_1/5/20` 共 30 个组合配置均指向存在的函数。

现有 `tests/strategies/test_ten_buy_signals.py` 必须继续通过，证明抽取 helper 或复用逻辑未改变买入策略。

## Non-Goals

- 不引入实盘订单、止盈止损引擎或持仓状态数据库。
- 不改变 `BrokerEngine` 的 `next_open` 执行规则。
- 不接入外部板块/龙头股数据源；卖讯二使用 `stock_pool[:2]`。
- 不新增可视化页面；策略结果继续通过现有 strategy-results 工作台查看。
- 不自动运行完整历史回测生成结果文件，除非后续用户明确要求。

## Open Decisions Resolved

- 接入方式选择「两者都要」：独立十大卖讯 + 买入策略叠加卖讯提前退出。
- 周线相关卖讯使用现有日线聚合周线能力。
- 龙头股相关卖讯使用当前 `stock_pool` 前两只股票作为本地可执行约定。
