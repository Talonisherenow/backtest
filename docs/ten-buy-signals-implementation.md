# 十大买讯策略实现映射

本文档说明 `docs/0504-十大买讯对应的量化公式.md` 中的 10 条买讯，如何映射到当前回测项目中的策略代码和回测 case。

原始文档负责定义买讯含义、触发公式和买入操作；代码实现负责把这些规则转换成项目标准信号：

```text
date, symbol, target_weight
```

这些信号由 legacy `PythonSignalProvider` 加载，之后可以继续交给
`BacktestEngine -> BrokerEngine` 执行，也可以通过 `LegacyStrategyPlanner`
适配进新的 `BacktestRunner -> ExecutionBackend` 路径。后续如果重写成原生新架构实现，应优先表达为
`SignalGenerator -> SignalScoreFrame`，再由 `PortfolioAllocator` 生成目标仓位。

## 文件关系

| 角色 | 文件 |
| --- | --- |
| 原始规则来源 | `docs/0504-十大买讯对应的量化公式.md` |
| 策略代码实现 | `strategies/ten_buy_signals.py` |
| 基础买入 case | `configs/ten_buy_signals/*.yaml` |
| 固定持有期 case | `configs/ten_buy_signals/hold_1/*.yaml`、`hold_5/*.yaml`、`hold_20/*.yaml` |
| 正例触发测试 | `tests/strategies/test_ten_buy_signals.py` |

每个 case 都使用同一个策略文件，只是 `signals.function` 指向不同函数：

```yaml
signals:
  type: python
  path: ../../strategies/ten_buy_signals.py
  function: generate_buy_signal_01
```

## 通用实现约定

### 数据入口

策略函数接收项目提供的 `StrategyContext`，主要使用：

| 字段 | 用途 |
| --- | --- |
| `context.bars` | 日线 OHLCV 数据 |
| `context.stock_pool` | 当前 case 的股票池 |
| `context.start_date` / `context.end_date` | 回测日期范围，由配置提供 |

`_prepare_daily_bars()` 会先做统一整理：

- 只保留 `stock_pool` 内股票；
- 将 `date` 转成 pandas 日期；
- 将 `open`、`high`、`low`、`close`、`volume` 转为数值；
- 按 `symbol,date` 排序。

### 公式基础工具

代码中把公式里的常用操作抽成 helper：

| 原始公式概念 | 代码 helper |
| --- | --- |
| `MA_N(X)_t`，含当日均线 | `_ma(bars, column, window)` |
| `MA_N(X)`，不含当日均线 | `_prev_ma(bars, column, window)` |
| `P_{t-k}`、`V_{t-k}` | `_shift(bars, column, periods)` |
| 过去 N 日最高，不含当日 | `_prev_max(bars, column, window)` |
| 过去 N 日最低，不含当日 | `_prev_min(bars, column, window)` |
| 过去 N 日最高，含当日 | `_rolling_max(bars, column, window)` |
| 日线转周线 | `_weekly_bars(daily)` |

周线使用 `W-FRI` 聚合：

- 周开盘价：本周第一根日线 `open`
- 周最高价：本周 `high.max()`
- 周最低价：本周 `low.min()`
- 周收盘价：本周最后一根日线 `close`
- 周成交量：本周 `volume.sum()`
- 周日期：本周最后一个实际交易日

### 信号输出

每个策略函数最终返回 `date,symbol,target_weight`。

`_with_target_weights()` 负责统一生成仓位权重：

- 单日单票默认上限是 `BASE_TARGET_WEIGHT = 0.20`；
- 如果同一天多只股票触发，会按触发数量平均分配，并限制单票不超过 20%；
- 返回结果满足 legacy `SignalFrame` 校验要求。

基础函数只生成买入目标权重；固定持有期函数会额外生成 `target_weight = 0` 的退出信号。

### 固定持有期退出

为了观察 1、5、20 个交易日持有期下的表现，策略文件为每条买讯自动生成 3 个包装函数：

```text
generate_buy_signal_01_hold_1
generate_buy_signal_01_hold_5
generate_buy_signal_01_hold_20
...
generate_buy_signal_10_hold_1
generate_buy_signal_10_hold_5
generate_buy_signal_10_hold_20
```

实现入口是 `_signals_with_fixed_holding()`。它先调用原始买讯函数生成入场信号，再根据交易日序列补一条退出信号：

```text
买讯信号日 S
下一交易日 B 实际买入
持有 N 个交易日，B 算第 1 天
第 N 个持有交易日 H 生成 target_weight = 0
H 的下一交易日在 legacy BrokerEngine 或 NativeSimulationBackend 中以 next_open 卖出
```

如果同一只股票在尚未完成上一笔固定持有期退出前再次触发买讯，包装逻辑会忽略后续重叠入场，避免同一持仓周期被重复买入信号打乱。若信号靠近回测末尾，未来交易日不足以完成卖出执行，则该入场会被跳过。

## 十条买讯映射

### 买讯一：旱地拔葱放量

| 项目 | 内容 |
| --- | --- |
| 原始文档位置 | 买讯一：旱地拔葱放量 |
| 回测 case | `configs/ten_buy_signals/buy_signal_01_volume_breakout.yaml` |
| 策略函数 | `generate_buy_signal_01` |
| 核心代码 | `previous_volume_ma5 = _prev_ma(..., "volume", 5)`；`close_ma30 = _ma(..., "close", 30)` |

原始公式要求当日成交量大于等于过去 5 日均量的 2 倍，并可选加“长期低迷”过滤。代码把这个可选过滤固定纳入条件：`close < MA30(close)`。

实现条件：

```text
volume_t >= 2 * MA5(volume, 不含当日)
close_t < MA30(close, 含当日)
```

触发后在当日生成买入信号。原始文档里的“收盘前 5 分钟”在当前项目里无法表达为分钟级成交，所以用日线信号日期表示，实际执行由回测配置的 `next_open` 处理。新 runtime 下该语义由 `ExecutionBackend` 承接；legacy 路径下由 `BrokerEngine` 承接。

### 买讯二：股价连续上涨多日

| 项目 | 内容 |
| --- | --- |
| 原始文档位置 | 买讯二：股价连续上涨多日 |
| 回测 case | `configs/ten_buy_signals/buy_signal_02_rising_price_pullback.yaml` |
| 策略函数 | `generate_buy_signal_02` |
| 核心代码 | `consecutive_3_up`、`four_of_five_up`、`ma10 > ma10_prev`、`volume_expands`、`near_ma10` |

原始公式由趋势确认和买入点两部分组成。代码把两者合并为同一天触发：

```text
(连续 3 日上涨 OR 5 日涨 4 天)
AND MA10_t > MA10_{t-1}
AND volume_t > 1.2 * volume_{t-1}
AND close_t 在 MA10 上方 0%-2% 区间内
```

`near_ma10` 对应原始文档中的“回调至 10 日均线附近，偏离度 <= 2%，且价格 >= 10 日均线”。

### 买讯三：周量缩价稳背离

| 项目 | 内容 |
| --- | --- |
| 原始文档位置 | 买讯三：周量缩价稳背离 |
| 回测 case | `configs/ten_buy_signals/buy_signal_03_weekly_volume_contraction.yaml` |
| 策略函数 | `generate_buy_signal_03` |
| 核心代码 | `_weekly_bars()`、`weekly_contracts`、`weekly_volume_new_low`、`daily_volume_rebound` |

这条买讯是“周线设置 + 下周日线确认”的组合。

周线设置条件：

```text
V_w < V_{w-1} < V_{w-2}
AND V_w <= 最近 8 周最低周量
AND close_w >= close_{w-1}
AND low_w >= 过去 4 周最低低点
```

日线确认条件：

```text
volume_d > 1.5 * MA5(volume, 不含当日)
AND close_d > close_{d-1}
```

代码先用周线找 setup，再用 `_first_daily_after_weekly_setups()` 在 setup 周结束后的 7 个自然日内寻找第一个满足日线确认的交易日，并在该日输出信号。

### 买讯四：利空不跌反涨

| 项目 | 内容 |
| --- | --- |
| 原始文档位置 | 买讯四：利空不跌反涨 |
| 回测 case | `configs/ten_buy_signals/buy_signal_04_bad_news_absorption.yaml` |
| 策略函数 | `generate_buy_signal_04` |
| 核心代码 | `close_rises_2`、`volume_up_today`、`volume_up_yesterday`、`below_ma200`、`breakout` |

原始文档说明如果没有事件数据，可以使用技术替代版。当前项目尚未接入利空事件数据，所以代码采用技术替代版，并把“突破近期高点”也纳入触发条件。

实现条件：

```text
close_{t-1} > close_{t-2}
AND close_t > close_{t-1}
AND volume_{t-1} > 1.5 * MA20(volume)_{t-1}
AND volume_t > 1.5 * MA20(volume)_t
AND close_t < MA200(close)_t
AND close_t > 过去 10 日 high 最高值
```

这里的突破使用 `high` 的过去 10 日最高价，不含当日。

### 买讯五：强势股再突破

| 项目 | 内容 |
| --- | --- |
| 原始文档位置 | 买讯五：强势股再突破 |
| 回测 case | `configs/ten_buy_signals/buy_signal_05_strong_stock_breakout.yaml` |
| 策略函数 | `generate_buy_signal_05` |
| 核心代码 | `prior_gain`、`drawdown_from_recent_high`、`close_ma20`、`prior_60_high` |

代码基本按原始公式落地：

```text
close_t / close_{t-20} - 1 > 0.30
AND (过去 21 日最高 close - close_t) / 过去 21 日最高 close <= 0.15
AND close_t >= MA20(close)_t
AND close_t > 过去 60 日最高 close，不含当日
```

原始文档提到“盘中突破前期高点”可买入；当前项目使用日线收盘数据，所以以收盘价突破作为信号确认。

### 买讯六：周震荡收高 + 均线上翻

| 项目 | 内容 |
| --- | --- |
| 原始文档位置 | 买讯六：周震荡收高 + 均线上翻 |
| 回测 case | `configs/ten_buy_signals/buy_signal_06_weekly_high_close_ma_turn.yaml` |
| 策略函数 | `generate_buy_signal_06` |
| 核心代码 | `weekly_range`、`closes_at_weekly_high`、`ma10 > ma10_prev`、`pullback_near_ma10` |

这条也是“周线设置 + 下周日线买点”。

周线设置条件：

```text
(high_w - low_w) / close_w > 0.07
AND close_w 约等于 high_w
AND MA10(close)_t > MA10(close)_{t-1}
```

代码里 `t` 是该周最后一个实际交易日。为了适配浮点价格，`close_w = high_w` 使用了很小容忍度。

日线买点：

```text
close_d >= MA10(close)_d
AND close_d <= MA10(close)_d * 1.02
```

同样通过 `_first_daily_after_weekly_setups()` 在 setup 周结束后的 7 个自然日内寻找第一个买点。

### 买讯七：低开高走大逆转

| 项目 | 内容 |
| --- | --- |
| 原始文档位置 | 买讯七：低开高走大逆转 |
| 回测 case | `configs/ten_buy_signals/buy_signal_07_gap_down_reversal.yaml` |
| 策略函数 | `generate_buy_signal_07` |
| 核心代码 | `sharp_drop`、`gap_down`、`long_lower_shadow`、`limit_up_reversal` |

实现条件：

```text
close_t / close_{t-3} - 1 < -0.08
AND open_t < low_{t-1}
AND (
  close_t > open_t 且 下影线 / 实体 > 0.5
  OR close_t >= round(close_{t-1} * 1.098, 2)
)
```

代码用 `close_{t-1}` 近似原始文档中的 `P_{t-1}`，用 `1.098` 近似 10% 涨停板。

原始文档的“次日确认：次日开盘价高于今日收盘价”目前没有实现，因为现有信号接口是按当前信号日输出目标权重，尚未提供“等下一根 K 线再确认”的策略状态封装。

### 买讯八：周线连红 + 量增

| 项目 | 内容 |
| --- | --- |
| 原始文档位置 | 买讯八：周线连红 + 量增 |
| 回测 case | `configs/ten_buy_signals/buy_signal_08_two_weekly_up_volume.yaml` |
| 策略函数 | `generate_buy_signal_08` |
| 核心代码 | `two_weekly_up_closes`、`prior_four_week_avg_volume`、`start_week_volume_expands` |

代码按周线公式落地：

```text
close_{w-1} > close_{w-2}
AND close_w > close_{w-1}
AND volume_{w-1} >= 1.25 * mean(volume_{w-2}, volume_{w-3}, volume_{w-4}, volume_{w-5})
```

当前实现把信号日期放在第二根周阳线确认的周末日期，也就是 `w` 周最后一个交易日。由于回测执行配置是 `next_open`，实际成交会在下一个交易日开盘处理，接近原始文档的“第三周初买入”。

### 买讯九：板块龙头领涨

| 项目 | 内容 |
| --- | --- |
| 原始文档位置 | 买讯九：板块龙头领涨 |
| 回测 case | `configs/ten_buy_signals/buy_signal_09_sector_leaders.yaml` |
| 策略函数 | `generate_buy_signal_09` |
| 核心代码 | `leaders = context.stock_pool[:2]`、`consecutive_3_big_up`、`four_up_days`、`five_day_gain` |

原始公式要求板块排名前两位龙头同步走强。当前项目配置模型只有 `stock_pool.symbols`，没有板块成分、龙头排名或行业强弱数据，所以代码约定：

```text
stock_pool 中前两只股票 = 龙头股 1 和 龙头股 2
```

对每只龙头计算强势条件：

```text
条件 A：连续 3 日单日涨幅 > 3%
OR
条件 B：5 日涨 4 天 且 5 日累计涨幅 > 10%
```

当同一交易日两只龙头都满足强势条件时，给两只龙头同时生成信号。

原始文档里的“布局板块内其他个股”尚未实现，因为这需要板块内其他股票、质量筛选和相对涨幅数据。

### 买讯十：超跌地心引力区放量

| 项目 | 内容 |
| --- | --- |
| 原始文档位置 | 买讯十：超跌地心引力区放量 |
| 回测 case | `configs/ten_buy_signals/buy_signal_10_oversold_gravity_volume.yaml` |
| 策略函数 | `generate_buy_signal_10` |
| 核心代码 | `ma30`、`ma72`、`gravity_line`、`oversold`、`volume_expands`、`bullish_close` |

实现条件：

```text
gravity_line_t = (MA30(close)_t + MA72(close)_t) / 2
close_t <= 0.8 * gravity_line_t
AND volume_t >= 2 * MA5(volume, 不含当日)
AND close_t > open_t
```

原始文档里的“-5% 止损”目前没有转换成退出信号。固定持有期 case 可用于观察 1、5、20 个交易日退出下的表现，其中 `hold_5` 可作为“持有 3-5 个交易日”这一说法的简化版本。

## 回测 case 如何连接策略

基础 10 个 YAML case 和固定持有期 30 个 YAML case 的共同结构是：

| 配置块 | 作用 |
| --- | --- |
| `project.name` | 生成 run id 和报告名 |
| `data` | 指定数据源、复权方式、日期范围、股票池 |
| `signals` | 指向 `strategies/ten_buy_signals.py` 中的某个基础函数或固定持有期函数 |
| `execution` | 使用项目现有 A 股交易设置和 `next_open` 执行 |
| `metrics` | 输出收益、年化、最大回撤、夏普、交易次数 |
| `report` | 每个买讯输出到独立目录 |

当前 40 个 case 使用相同占位股票池：

```yaml
stock_pool:
  symbols:
    - 000001.SZ
    - 600519.SH
```

后续确定真实验证范围后，只需要批量替换每个 case 的 `data.start_date`、`data.end_date`
和 `stock_pool.symbols`；如果使用随机抽样生成的批次文件，也可以改成
`stock_pool.symbols_file` 指向 `backtest data sample-pool` 的输出。

固定持有期 case 的目录含义：

| 目录 | 含义 |
| --- | --- |
| `configs/ten_buy_signals/hold_1/` | 实际买入后持有 1 个交易日，再发出退出信号 |
| `configs/ten_buy_signals/hold_5/` | 实际买入后持有 5 个交易日，再发出退出信号 |
| `configs/ten_buy_signals/hold_20/` | 实际买入后持有 20 个交易日，再发出退出信号 |

## 测试覆盖关系

`tests/strategies/test_ten_buy_signals.py` 做三类验证：

1. 为每条买讯构造一段最小正例 K 线，确认对应 `generate_buy_signal_XX()` 至少能在应触发日期生成信号。
2. 扫描 `configs/ten_buy_signals/buy_signal_*.yaml`，确认正好有 10 个 case，且每个 case 指向的策略函数真实存在。
3. 验证 `hold_1`、`hold_5`、`hold_20` 会在预期交易日生成 `target_weight = 0`，并扫描 30 个固定持有期 case 是否指向真实函数。

这些测试验证的是“公式到 legacy `SignalFrame`”的转换，不验证真实行情上的收益表现，也不验证新架构里的 `SignalGenerator -> PortfolioAllocator` 拆分。

## 当前实现边界

当前版本优先把 10 条买讯落成可回测的信号 case，以下部分需要等数据和执行需求进一步明确后扩展：

- 分钟级买入点：原始文档多处提到“收盘前 5 分钟”或“盘中突破”，当前项目使用日线信号和 `next_open` 执行。
- 退出策略：固定持有期退出已支持 1、5、20 个交易日；止损、前高下方止损、次日确认等条件退出尚未实现。
- 事件数据：买讯四目前使用技术替代版，没有接利空事件源。
- 板块数据：买讯九暂以 `stock_pool` 前两只股票作为龙头，没有真实板块成分和龙头排名。
- 资金管理参数：单票默认 20% 目标仓位是代码约定，后续可以改为从 `context.params` 或配置读取。

这份映射文档可以作为后续接入真实数据、补充止损/条件退出规则和扩展板块/事件数据时的索引。
