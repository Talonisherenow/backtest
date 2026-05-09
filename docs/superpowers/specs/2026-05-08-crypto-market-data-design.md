# 加密货币历史行情接口设计

日期：2026-05-08
状态：已获口头批准，开发中
分支：`feat/crypto-market-data`
工作目录：`/Users/Tyrone.Shi/code-private/backtest`

## 1. 背景

当前系统已经有 A 股 AkShare 日线数据链路，也已经在通用交易架构中引入了
`Instrument`、`TargetPortfolioFrame`、`OrderIntent`、`PortfolioState` 和
`OrderLedger`。下一步要把加密货币纳入通用标的体系，但第一版不直接做实盘交易，
而是先接入历史 OHLCV 数据。

这样做的原因是：策略研究、信号生成和后续回测都依赖稳定的数据缓存；真实下单还需
`ExecutionAdapter`、风控、凭证管理、限频、拒单和对账能力，不能和历史数据接口混在一起。

## 2. 第一版目标

第一版实现：

- 通过 CCXT 获取加密货币现货历史 OHLCV。
- 继续复用现有 `DataProvider -> DataSyncService -> ParquetBarStore -> DataCatalog` 链路。
- 支持 `BTC/USDT`、`ETH/USDT` 这类 CCXT unified symbol。
- 支持加密货币代表性周期：`1d`、`4h`、`1h`、`30m`、`15m`、`5m`、`1m`。
- 加密货币缓存使用 `adjust=none`。
- 缓存 catalog 的 `source` 使用 `ccxt:<exchange>`，避免不同交易所数据互相覆盖。
- 对当前未收盘的最后一根 K 线默认丢弃，避免回测使用未完成数据。
- 更新设计文档、数据文档、CLI 文档和 `docs/ai-handoff.md`。

第一版不做：

- 真实下单、撤单、查单或账户查询。
- API key、secret、子账户和权限管理。
- 合约、永续、杠杆、资金费率、标记价格、指数价格。
- Tick、逐笔成交、订单簿或 WebSocket 实时数据。
- 完整 crypto 回测撮合器。当前 `BrokerEngine` 仍是 A 股撮合器。
- 多交易所数据自动仲裁。

## 3. 时间级别设计

推荐默认研究周期：

```text
1d   长期趋势、跨市场比较、低频策略
4h   加密货币波段策略代表性周期
1h   短中期策略主力周期
15m  日内策略和短线信号
5m   更细的执行择时分析
1m   支持但不建议默认大范围拉取
```

系统已有 `1d`、`1m`、`5m`、`15m`、`30m`。本次新增 `1h` 和 `4h`。旧的
`60m` 输入保留兼容，会归一化为标准 `1h`。

CCXT 官方文档说明：OHLCV 使用 `fetchOHLCV` / `fetch_ohlcv`；交易所是否支持 K
线由 `has['fetchOHLCV']` 判断；可用周期看 `exchange.timeframes`；`since` 是 UTC
毫秒时间戳；不传 `since` 时返回区间由交易所自行决定；当前未收盘 K 线可能不完整。
设计和实现必须遵守这些约束。

参考：`https://github.com/ccxt/ccxt/wiki/manual`

## 4. 数据合同

### 4.1 Symbol

A 股 symbol 继续保持：

```text
000001.SZ
600519.SH
430017.BJ
```

加密货币现货 symbol 使用 CCXT unified symbol：

```text
BTC/USDT
ETH/USDT
SOL/USDT
BTC/USD
```

`normalize_symbol()` 第一版允许两类格式：

- 原 A 股格式。
- 简单 crypto spot pair：`BASE/QUOTE`，统一转大写。

不在第一版支持 `BTC/USDT:USDT` 这类合约 symbol。

### 4.2 BarFrame

继续使用现有 `BarFrame`：

```text
date, symbol, open, high, low, close, volume, amount, frequency, adjust
```

加密货币约定：

- `date`：UTC 时间，保存为 timezone-naive pandas datetime。
- `symbol`：如 `BTC/USDT`。
- `volume`：CCXT 返回的成交量，通常是 base asset 数量。
- `amount`：第一版用 `close * volume` 估算 quote notional，不宣称是交易所精确成交额。
- `frequency`：系统内部频率，例如 `1h`、`4h`。
- `adjust`：固定为 `none`。

### 4.3 缓存路径

现有路径：

```text
data/bars/frequency=1d/adjust=qfq/symbol=000001.SZ/year=2025/bars.parquet
```

加密货币 symbol 里有 `/`，不能直接作为目录名。缓存路径中的 symbol 使用 URL percent
encoding：

```text
data/bars/frequency=4h/adjust=none/symbol=BTC%2FUSDT/year=2025/bars.parquet
```

Parquet 内容和 catalog 中的 symbol 仍保留 `BTC/USDT`。

## 5. 配置和 CLI

现有配置保留 `stock_pool` 字段以兼容旧代码。第一版 crypto 配置示例：

```yaml
project:
  name: crypto-btc-usdt
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
signals:
  type: file
  path: signals/demo.csv
execution:
  timing: next_open
  initial_cash: 100000
  commission_rate: 0.001
  min_commission: 0
  stamp_tax_rate: 0
  slippage_rate: 0.0005
  board_lot_size: 1
metrics:
  builtin:
    - total_return
report:
  output_dir: runs
  html: true
  charts: true
```

`backtest data sync` 选择 provider：

- `source: akshare` -> `AkShareProvider`
- `source: ccxt` + `exchange: <id>` -> `CCXTOHLCVProvider(exchange_id=<id>)`

sync 和 coverage 传给 catalog 的 source：

```text
akshare
ccxt:binance
ccxt:okx
ccxt:kraken
```

如果 `source: ccxt` 但没有 `exchange`，CLI 应给出清晰错误。

## 6. Provider 行为

`CCXTOHLCVProvider` 放在：

```text
backtest/data/ccxt_provider.py
```

行为：

1. 懒加载 `ccxt`，便于测试注入 fake exchange。
2. 创建 exchange 时启用 `enableRateLimit=True`。
3. 调用 `exchange.load_markets()`。
4. 检查 `exchange.has['fetchOHLCV']`。
5. 检查请求的 symbol 是否在 `exchange.markets`。
6. 检查请求周期是否在 `exchange.timeframes`。
7. 显式传 `since`，按 `limit` 分页直到超过 `end_date`。
8. 丢弃当前未收盘 K 线。
9. 把 OHLCV 转成 `BarFrame` 并调用 `validate_bar_frame()`。

空数据返回空 `BarFrame`；`DataSyncService` 继续把空数据视为任务失败。

## 7. 与回测的关系

本次完成后，系统可以缓存加密货币 OHLCV，并把它作为策略研究输入。

但不能宣称完整 crypto 回测已经完成，因为当前 `BrokerEngine` 仍然内置 A 股假设：

- 整数股数量。
- `board_lot_size`。
- A 股费用模型。
- T+1 可卖限制。
- 涨跌停和停牌字段。

后续 crypto 回测要单独做：

```text
CryptoBrokerEngine 或 BacktestSimulationAdapter
CryptoFeeModel
fractional quantity
T+0 selling
TradingRule-driven lot/tick/min notional
ExecutionReport -> PortfolioState accounting
```

## 8. 测试策略

测试不访问真实交易所网络，全部使用 fake exchange：

- symbol normalization 支持 A 股和 crypto spot pair。
- 不合法 symbol 继续拒绝。
- `Frequency.HOUR_4` 可被 Pydantic/validator 接受。
- `ParquetBarStore` 对 `BTC/USDT` 使用安全路径并能读回。
- `CCXTOHLCVProvider` 正确分页、映射时间级别、计算 `amount`、丢弃未收盘 K 线。
- provider 对不支持 OHLCV、不存在 symbol、不支持周期、非 `adjust=none` 给出明确错误。
- CLI 对 `source=ccxt` 选择 CCXT provider，并以 `ccxt:<exchange>` 写 catalog source。
- A 股现有测试保持通过。
