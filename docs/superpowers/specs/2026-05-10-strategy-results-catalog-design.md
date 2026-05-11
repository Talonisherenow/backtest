# Strategy Results Service Design

日期：2026-05-10
状态：服务化第一版已实现
分支：`feat/strategy-planning-architecture`
工作目录：`/Users/Tyrone.Shi/code-private/backtest`

## 1. 背景

上一版 `Strategy Results Catalog` 通过生成 `strategy_results_index.html` 和一批 `strategy_account_viewer_*.html` / `strategy_order_drilldown_*.html` 文件来管理回测结果。这个方案虽然能导航，但不符合结果管理的使用方式：跑完回测后不应该再批量生成 HTML。

新的方向是把 viewer 变成本地后台应用。回测过程只写数据产物；用户启动后台应用后打开一个固定页面，页面自动从后台 API 读取策略列表、回测摘要和按需详情。

## 2. 目标

第一版服务化结果工作台需要做到：

- 跑完回测后不生成任何 HTML。
- 启动 `backtest chart serve-workbench` 后从 `/strategy-results` 打开固定结果页。
- `backtest chart serve-results` 继续保留为单独结果服务入口。
- 页面自动调用 API 拉取策略列表和回测结果摘要。
- 点击某条回测结果时，后台按需读取 `orders/equity_curve/bars` 并返回动态 account viewer。
- 点击某个订单或标的时，后台按需返回动态 drilldown viewer。
- 复用已收敛的 account viewer 和 order drilldown viewer，不复制业务计算。

## 3. 非目标

第一版不做：

- 不引入数据库、用户权限、远程部署或多用户服务。
- 不要求回测结束阶段写 HTML。
- 不把所有 K 线和订单数据一次性塞进 catalog 首页。
- 不实现复杂参数搜索 UI、跨策略归因或组合归因。
- 不删除已有静态写出函数；它们可以保留为测试/调试工具，但不作为主路径。

## 4. 用户流程

```text
运行回测
  -> 写出 summary.csv / orders.csv / equity_curve.csv / trades.csv / targets.csv / signals.csv

启动结果服务
  -> backtest chart serve-workbench --results-root runs/ten_buy_signals/new_runtime_native_20260510

打开页面
  -> http://127.0.0.1:8767/strategy-results

页面加载
  -> GET /api/strategy-results

点击回测结果
  -> /strategy-results/account?case_id=signal_02_hold_20

点击订单
  -> /strategy-results/drilldown?case_id=signal_02_hold_20#symbol=002966.SZ&order_id=order-002779
```

## 5. 服务模块

新增：

```text
backtest/charts/strategy_results_service.py
backtest/charts/strategy_results_server.py
```

### 5.1 StrategyResultsService

负责发现和读取结果数据：

```python
class StrategyResultsService:
    def __init__(self, *, results_roots: list[Path], bars_root: Path) -> None: ...
    def catalog(self) -> dict[str, Any]: ...
    def account_payload(self, case_id: str) -> dict[str, Any]: ...
    def drilldown_payload(self, case_id: str, default_symbol: str | None = None) -> dict[str, Any]: ...
```

规则：

- `catalog()` 扫描 `results_roots` 下的 `summary.csv`，过滤出有策略回测指标的 summary。
- 对 aggregate runtime 结果，`case_id` 来自 `orders.csv/equity_curve.csv` 中的实际 `case_id`，如 `signal_02_hold_20`。
- `account_payload()` 只在用户点击某条结果时读取对应 case 的订单、账户曲线和相关 K 线。
- `drilldown_payload()` 只在用户进入单标的详情时读取对应 case 的订单和相关 K 线。

### 5.2 Strategy Results Server

负责 HTTP 路由：

```text
GET /strategy-results
  返回动态 catalog app shell

GET /api/strategy-results
  返回 catalog JSON

GET /strategy-results/account?case_id=...
  返回动态生成的 Strategy Account Viewer HTML

GET /api/strategy-results/account?case_id=...
  返回 account payload JSON

GET /strategy-results/drilldown?case_id=...
  返回动态生成的 Strategy Order Drilldown HTML

GET /api/strategy-results/drilldown?case_id=...&symbol=...
  返回 drilldown payload JSON
```

## 6. Catalog 页面

`Strategy Results Catalog` 首页是 app shell，不再内嵌完整结果 payload。它启动后调用：

```javascript
fetch("/api/strategy-results")
```

然后渲染：

- 策略列表。
- 当前策略的多次回测结果。
- 每条结果的 `Open Result` 链接，指向 `/strategy-results/account?case_id=...`。

## 7. 详情页面

Account viewer 和 drilldown viewer 仍复用已有 HTML 渲染函数，但由后台服务按需返回，不落盘。

动态链接规则：

- Account viewer 的返回 catalog 链接：`/strategy-results`
- Account viewer 的 drilldown 链接：`/strategy-results/drilldown?case_id=<case_id>`
- Drilldown viewer 的返回 account 链接：`/strategy-results/account?case_id=<case_id>`

## 8. CLI

推荐主入口：

```bash
backtest chart serve-workbench \
  --results-root runs/ten_buy_signals/new_runtime_native_20260510 \
  --a-share-bars-root data/bars \
  --bitget-bars-root data/crypto/bitget/bars \
  --host 127.0.0.1 \
  --port 8767
```

单独结果服务入口：

```bash
backtest chart serve-results \
  --results-root runs/ten_buy_signals/new_runtime_native_20260510 \
  --bars-root data/bars \
  --host 127.0.0.1 \
  --port 8766
```

`backtest chart strategy-results --output ...` 不是主路径；后续可以移除或保留为调试工具。第一版应避免在正常工作流中使用它。

## 9. 错误处理

- 没有发现结果时，catalog API 返回空列表，不报 500。
- 请求不存在的 `case_id` 时，API 返回 400，并包含错误信息。
- 某只标的缺少 bars 时，使用已有订单和账户曲线尽量返回可渲染 payload；无法渲染时返回 400。
- 服务端不写 HTML 文件，因此不存在生成文件清理问题。

## 10. 测试

需要覆盖：

- `StrategyResultsService.catalog()` 能从 summary 发现策略和回测结果。
- `StrategyResultsService.account_payload(case_id)` 能按需读取 orders/equity/bars 并生成 account payload。
- `StrategyResultsService.drilldown_payload(case_id, symbol)` 能生成 drilldown payload。
- Catalog app shell 包含 `/api/strategy-results` fetch 逻辑。
- CLI `backtest chart serve-workbench` 能把 result roots、K-line sources、host、
  port 和 window size 传给 combined server。
- CLI `backtest chart serve-results` 能把 root、bars root、host、port 传给 standalone server。
- 现有 account/drilldown/chart 测试继续通过。

## 11. 验收标准

- 跑完回测后不需要生成任何 HTML。
- 启动 `backtest chart serve-workbench` 后，打开 `http://127.0.0.1:8767/strategy-results` 能看到策略列表。
- 点击 `signal_02` 下的 `hold_20` 能打开动态 account viewer。
- 在 account viewer 中点击订单能打开动态 drilldown viewer。
- `runs/charts` 下不再需要批量生成的 `strategy_account_viewer_signal_*_hold_*.html` 和 `strategy_order_drilldown_signal_*_hold_*.html`。
