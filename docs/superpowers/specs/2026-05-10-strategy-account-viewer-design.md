# Strategy Account Viewer Design

日期：2026-05-10
状态：已实现初版
分支：`feat/strategy-planning-architecture`
工作目录：`/Users/Tyrone.Shi/code-private/backtest`

## 1. 背景

单标的订单 K 线视图已经用于观察某只股票的买点、卖点和局部订单表现。这个视图不适合继续展示账户级资金曲线，因为单标的订单与全账户 `cash/equity/return` 混在一起会造成语义误解。

本设计新增一个策略账户级视图，用于观察一次策略回测 case 的整体账户表现。

## 2. 目标

第一版策略账户级视图需要展示：

- 策略持仓中不同标的在回测时间线内的持仓市值变化。
- 账户维度的 `cash` 和 `equity` 变化。
- 策略整体收益率变化。
- 整个回测过程的订单列表。

该视图独立于单标的订单 K 线视图，后续可以继续增加筛选、联动、高亮和标的聚焦。

## 3. 非目标

第一版不做：

- 不把账户级图层重新塞回单标的订单 K 线图。
- 不实现复杂的归因分析、行业聚合或风险模型。
- 不实现服务端分页和动态加载。
- 不替换现有回测引擎。
- 不要求本次批量结果已经导出 `positions.csv`。

## 4. 数据来源

当前批量回测目录包含：

```text
orders.csv
equity_curve.csv
trades.csv
signals.csv
targets.csv
summary.csv
summary.json
```

其中 `equity_curve.csv` 是账户级数据，可以直接生成 `cash/equity/return` 曲线。当前目录没有 `positions.csv`，因此第一版从 `orders.csv + bars` 重建每日持仓市值。

长期建议：回测结果应直接导出 `positions.csv` 或更完整的 `position_values.csv`，账户级视图优先消费这些标准产物；从订单重建只作为兼容路径。

## 5. Payload 契约

新增模块：

```text
backtest/charts/strategy_account_viewer.py
```

核心函数：

```python
build_strategy_account_payload(
    *,
    bars: pd.DataFrame,
    orders: pd.DataFrame,
    equity_curve: pd.DataFrame,
    case_id: str | None = None,
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
    max_position_symbols: int | None = None,
) -> dict[str, Any]
```

Payload 结构：

```text
{
  title: str,
  case_id: str,
  account_curve: [
    {date, equity, cash, return}
  ],
  position_value_series: [
    {
      symbol: str,
      points: [
        {date, shares, market_value}
      ]
    }
  ],
  orders: [
    {date, symbol, side, filled_shares, price, fee_total, notional, status, reason}
  ],
  summary: {
    start_date,
    end_date,
    symbol_count,
    order_count,
    filled_order_count,
    initial_equity,
    latest_equity,
    latest_cash,
    total_return
  },
  metadata: dict
}
```

`position_value_series` 默认展开所有标的，并按单个标的全周期峰值持仓市值从高到低排序。若调用方显式传入 `max_position_symbols`，则只保留峰值持仓市值最高的前 N 个标的，其余标的聚合为 `Other`；`Other` 在 payload 中保留 `members`，方便后续详情面板或调试使用。

## 6. 持仓市值重建规则

重建规则与当前 native simulation 的账户语义保持一致：

- 只使用 `status in {"filled", "adjusted"}` 且 `filled_shares > 0` 的订单。
- `buy` 增加持仓股数，`sell` 减少持仓股数。
- 同一交易日先应用当日成交订单，再用当日收盘价计算市值。
- 若某只标的当日没有收盘价，沿用最近一次可用收盘价。
- 若没有可用收盘价但当日有成交价，用成交价作为临时估值。
- 账户时间线优先使用 `equity_curve` 的日期；无账户曲线时使用订单和行情日期合集。

## 7. 页面布局

```text
[Header / Summary]
  case_id, time range, symbol count, orders, latest equity, cash, total return

[Holdings Value]
  多标的持仓市值曲线，Top N + Other

[Equity/Cash]
  账户权益和现金两条曲线

[Return]
  策略整体收益率曲线

[Order List]
  全回测订单列表
```

## 8. 验证标准

- 单元测试覆盖从订单重建持仓市值。
- 单元测试覆盖账户收益率从 `equity_curve` 计算。
- 单元测试覆盖 HTML 包含持仓市值、账户资金、收益率和全订单列表四块。
- 持仓市值曲线保留市值为 0 的区间，让持仓进入和退出在时间线上连续可见。
- 页面使用三张独立 Plotly 图：`Holdings Value`、`Equity/Cash`、`Return` 各自渲染图例、时间刻度和缩放状态，不在曲线末端追加贴线标签。三张图的标题统一放在卡片顶部，使用与 `Order List` 相同层级的标题栏；Plotly 图内不再渲染小标题 annotation。
- `Holdings Value` 默认展示所有标的，不生成 `Other` 聚合线；图例使用自定义分页，每页最多 3 行，顺序与 payload 一致，即按全周期峰值持仓市值降序排列。每页列数根据图例区域实际宽度动态计算，避免被页码和翻页按钮裁切。
- `Holdings Value` 图例支持资产级筛选：单击切换某个资产显示/隐藏；双击只显示该资产；当页面已经只显示该资产时，再次双击恢复全部资产显示。
- 三张图统一使用 Plotly `x unified` hover：tooltip 顶部显示日期，内容行只显示 `图例 : value`，不重复日期或字段说明。`Holdings Value` 的 hover 只展示当日市值大于 0 的标的，市值为 0 的标的不进入 hover 列表，同时 hover 图例色条需要保持清晰可辨。
- 页面不渲染单独的 `Other includes` 文本块；若调用方显式启用聚合，`Other.members` 只作为结构化元数据保留。
- 对示例 case `signal_02_hold_20` 生成 HTML，并用 headless Chrome 截图验证页面可渲染。
