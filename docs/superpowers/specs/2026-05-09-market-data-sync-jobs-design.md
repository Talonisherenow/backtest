# Market Data Sync Jobs 设计

日期：2026-05-09
状态：待用户审核
分支：`feat/crypto-market-data`
工作目录：`/Users/Tyrone.Shi/code-private/backtest`

## 1. 背景

当前项目已经具备单次行情同步链路：

```text
DataProvider -> DataSyncService -> ParquetBarStore -> DataCatalog
                         |
                         v
                  CrawlTaskManager
```

`CCXTOHLCVProvider` 已经能通过 CCXT 拉取单个交易所、单个或少量 symbol、单个
frequency、一段日期范围的历史 OHLCV。`backtest data sync` 已经能从一个
backtest config 触发一次数据同步。

但实际跑加密货币 3 年多周期数据时，仍然需要临时脚本处理：

- 多 symbol 批量同步；
- 多 frequency 批量同步；
- 请求间隔和交易所限流；
- 网络错误、超时和 `429 Too Many Requests` 后的重试；
- 批量任务失败后继续执行剩余任务；
- 任务运行结果汇总为 `summary.csv` 和 `summary.json`；
- 后续被 cron、launchd、容器任务或守护进程定期调用。

这些能力不应该长期留在一次性脚本里。行情缓存是回测和交易系统的数据生产入口，
需要沉淀成项目内可测试、可复用、可运维的任务编排层。

## 2. 目标

本阶段新增一个通用的 Market Data Sync Job 能力：

- 用独立 job 配置描述批量行情同步任务；
- 支持 `symbol x frequency` 展开；
- 复用现有 `DataSyncService`、`ParquetBarStore`、`DataCatalog` 和
  `CrawlTaskManager`；
- 支持 CCXT crypto 历史 OHLCV 批量同步；
- 支持请求间隔、失败重试、失败后继续执行；
- 输出结构化运行结果；
- 提供 CLI 入口，便于人工触发和外部定时任务调用；
- 保持 runner 与 Typer CLI 解耦，为后续守护进程复用同一套核心逻辑预留边界；
- 更新数据文档、CLI 文档和 `docs/ai-handoff.md`。

本阶段不做：

- 自动选择或切换交易所；
- 常驻 daemon；
- WebSocket 实时行情；
- tick、逐笔成交、订单簿、资金费率、合约数据；
- 深度数据质量检查，例如完整分钟级缺口扫描、异常价格识别；
- 把大体积 parquet 行情文件纳入 git 提交；
- 真实交易 API、下单、撤单或账户查询。

## 3. 设计原则

### 3.1 数据任务和回测配置解耦

现有 backtest config 的 `data` 字段服务于一次回测或一次单频率数据同步。批量数据生产
有不同的生命周期：它可能每天定时跑，可能覆盖多个 frequency，也可能只刷新缓存而不
运行回测。

因此新增独立的 data job 配置，而不是把多周期、多 symbol、重试和输出目录全部塞进
现有 backtest config。

### 3.2 Runner 复用现有同步服务

第一版 `MarketDataJobRunner` 不重新实现 catalog、task、store 写入规则。每个
symbol/frequency item 仍然调用现有 `DataSyncService.sync()`。这样可以继续复用：

- source-aware missing range；
- retrying task 优先执行；
- `BarFrame` 校验；
- parquet 分区写入；
- catalog coverage upsert；
- task 成功和失败状态。

### 3.3 CLI 是入口，不是业务核心

CLI 负责读取配置、创建 provider/store/catalog/tasks、调用 runner、展示结果。核心
job runner 不依赖 Typer，因此未来可以直接被 daemon、调度器或测试代码调用。

### 3.4 第一版偏稳定，不做过度自动化

交易所选择、数据质量深度检测、增量刷新策略都可以继续演进。第一版优先解决明确痛点：
把批量拉取、重试、限流、结果产物从临时脚本提炼为可维护能力。

## 4. Job 配置

新增配置文件建议放在：

```text
configs/data_jobs/crypto_bitget_core.yaml
```

示例：

```yaml
name: crypto-bitget-core
source: ccxt
exchange: bitget

symbols:
  - BTC/USDT
  - ETH/USDT
  - SOL/USDT
  - BNB/USDT

frequencies:
  - 1d
  - 4h
  - 60m
  - 30m
  - 15m
  - 5m
  - 1m

adjust: none
start_date: "2023-05-08"
end_date: "2026-05-08"

bars_root: data/crypto/bars
metadata: data/crypto/metadata.sqlite
output_dir: runs/crypto_market_data/bitget_core

retry:
  max_attempts: 5
  request_delay_seconds: 0.5
  failure_cooldown_seconds: 30
  continue_on_error: true
```

字段语义：

```text
name                         任务名，用于日志和产物目录识别
source                       数据源，第一版支持 akshare 和 ccxt 的结构，示例优先 ccxt
exchange                     CCXT exchange id；source=ccxt 时必填
symbols                      需要同步的 symbol 列表
frequencies                  需要同步的系统内部 frequency 列表
adjust                       复权模式；crypto 必须是 none
start_date / end_date        同步日期范围
bars_root                    parquet 行情缓存根目录
metadata                     SQLite metadata 路径
output_dir                   job 结果输出目录
retry.max_attempts           单个 item 最大尝试次数
retry.request_delay_seconds  每个 item 执行前后的基础间隔
retry.failure_cooldown_seconds 失败后下一次重试前等待时间
retry.continue_on_error      单个 item 最终失败后是否继续跑剩余 item
```

## 5. 代码结构

新增：

```text
backtest/data/jobs.py
```

负责：

- `RetryConfig`
- `DataSyncJobConfig`
- `JobItem`
- `JobItemResult`
- `JobResult`
- `MarketDataJobRunner`
- `load_data_sync_job_config(path: Path) -> DataSyncJobConfig`

修改：

```text
backtest/cli/data.py
```

新增命令：

```bash
backtest data sync-job --job configs/data_jobs/crypto_bitget_core.yaml
```

新增测试：

```text
tests/data/test_data_jobs.py
```

新增示例配置：

```text
configs/data_jobs/crypto_bitget_core.yaml
```

更新文档：

```text
docs/data-ingestion.md
docs/cli.md
docs/ai-handoff.md
```

## 6. 核心模型

### 6.1 RetryConfig

```python
class RetryConfig(BaseModel):
    max_attempts: int = Field(default=3, ge=1)
    request_delay_seconds: float = Field(default=0.0, ge=0)
    failure_cooldown_seconds: float = Field(default=0.0, ge=0)
    continue_on_error: bool = True
```

`request_delay_seconds` 用于降低交易所限流风险。`failure_cooldown_seconds` 用于
`429`、超时或临时网络错误后的冷却。第一版不区分异常类型，所有失败都按同一规则重试。

### 6.2 DataSyncJobConfig

```python
class DataSyncJobConfig(BaseModel):
    name: str
    source: str
    exchange: str | None = None
    symbols: list[str]
    frequencies: list[Frequency]
    adjust: AdjustMode = AdjustMode.QFQ
    start_date: date
    end_date: date
    bars_root: Path = Path("data/bars")
    metadata: Path = Path("data/metadata.sqlite")
    output_dir: Path = Path("runs/data_jobs")
    retry: RetryConfig = Field(default_factory=RetryConfig)
```

校验规则：

- `name` 非空；
- `source` 统一转小写；
- `symbols` 至少一个，并使用 `normalize_symbol()`；
- `frequencies` 至少一个；
- `end_date >= start_date`；
- `source=ccxt` 时 `exchange` 必填并转小写；
- `source=ccxt` 时 `adjust` 必须为 `none`。

### 6.3 JobItem

每个 item 是一次可独立重试的数据同步：

```text
symbol + frequency + adjust + source + start_date + end_date
```

例如：

```text
BTC/USDT 1m none ccxt:bitget 2023-05-08..2026-05-08
```

### 6.4 JobItemResult

记录每个 item 的执行结果：

```text
job_name
source
exchange
symbol
frequency
adjust
start_date
end_date
status
attempts
rows
error
started_at
finished_at
```

`status` 使用：

```text
success
failed
skipped
```

第一版不主动生成 `skipped`，但保留状态用于后续 dry-run 或 coverage-complete 快速跳过。

### 6.5 JobResult

记录整次任务：

```text
name
started_at
finished_at
items
```

提供：

- `total_items`
- `success_count`
- `failed_count`
- `total_rows`
- `to_frame()`
- `write(output_dir)`

`write(output_dir)` 输出：

```text
summary.csv
summary.json
```

## 7. Runner 行为

`MarketDataJobRunner.run(config)` 流程：

1. 创建 `JobResult`。
2. 按配置顺序展开 `symbols x frequencies`。
3. 对每个 item 执行最多 `max_attempts` 次。
4. 每次尝试前应用 `request_delay_seconds`。
5. 调用 `DataSyncService.sync()`。
6. 成功后从 `DataCatalog.inventory()` 聚合当前 item 对应 source/symbol/frequency/adjust 的
   rows，写入 `JobItemResult`。
7. 失败后记录错误。如果还有剩余尝试，等待 `failure_cooldown_seconds` 后重试。
8. 单个 item 最终失败时：
   - `continue_on_error=true`：记录失败并继续后续 item；
   - `continue_on_error=false`：记录失败，写出已有 summary，然后抛出异常让 CLI 失败退出。
9. 所有 item 结束后写出 `summary.csv` 和 `summary.json`。

Runner 不直接知道 CCXT，也不直接操作 parquet 文件。它只编排 `DataSyncService` 和
`DataCatalog`。

## 8. Source 规则

job 配置中的 `source` 和 catalog 中的 source 需要区分：

```text
source=akshare -> catalog source: akshare
source=ccxt + exchange=bitget -> catalog source: ccxt:bitget
```

这与现有 CLI 逻辑保持一致，避免不同交易所的数据覆盖度互相隐藏。

## 9. CLI 设计

新增命令：

```bash
backtest data sync-job --job configs/data_jobs/crypto_bitget_core.yaml
```

命令行为：

- 读取 job YAML；
- 创建 provider：
  - `source=akshare` -> `AkShareProvider()`
  - `source=ccxt` -> `CCXTOHLCVProvider(exchange_id=exchange)`
- 创建 `MetadataStore`、`DataCatalog`、`CrawlTaskManager`、`ParquetBarStore`；
- 创建 `DataSyncService`；
- 调用 `MarketDataJobRunner.run()`；
- 打印简短汇总：

```text
Data job crypto-bitget-core complete: total=28 success=28 failed=0 rows=1844765
Summary written to runs/crypto_market_data/bitget_core/summary.csv
```

如果存在失败：

- `continue_on_error=true`：命令打印失败数量，并以非 0 退出码退出，方便调度器告警；
- `continue_on_error=false`：第一个最终失败 item 后结束并非 0 退出。

## 10. 定时任务扩展

第一版不实现守护进程，但 CLI 应该可以被外部调度器直接调用。

cron 示例：

```bash
cd /Users/Tyrone.Shi/code-private/backtest && \
uv run backtest data sync-job --job configs/data_jobs/crypto_bitget_core.yaml
```

launchd、容器任务、Airflow 或未来项目内 daemon 都应该复用同一个
`MarketDataJobRunner`。后续如果要做项目内 daemon，可以新增：

```text
backtest/data/scheduler.py
```

并让 scheduler 只负责触发时机，实际同步仍交给 runner。

## 11. 错误处理

第一版错误处理策略：

- 单个 item 的异常会进入 retry 循环；
- 每次失败记录最后一个错误字符串；
- 最终失败写入 summary；
- summary 在提前中断前也要写出；
- 不吞掉 CLI 退出码，避免定时任务静默失败；
- 不把 provider 内部异常改写成模糊错误，保留原始 message 便于定位交易所问题。

常见失败：

```text
网络超时
交易所 429 限流
symbol 不存在
frequency 不支持
provider 返回空数据
metadata 或 parquet 写入失败
```

其中 symbol 不存在、frequency 不支持属于配置错误，重试通常不会修复；第一版仍按统一
retry 处理，后续可以基于异常类型引入不可重试错误分类。

## 12. 测试方案

单元测试不访问真实交易所。

重点测试：

- YAML 配置加载和字段校验；
- `source=ccxt` 但缺少 `exchange` 会失败；
- `source=ccxt` 且 `adjust != none` 会失败；
- runner 按 `symbols x frequencies` 展开 item；
- 单个 item 成功后生成 `success` result；
- provider/service 第一次失败、第二次成功时 attempts 为 2；
- `continue_on_error=true` 时一个 item 失败后继续执行剩余 item；
- `continue_on_error=false` 时最终失败后中断；
- summary CSV/JSON 写出，并包含 symbol、frequency、status、attempts、rows、error。

实现测试时使用 fake service 或 fake provider，避免网络依赖和交易所限流造成不稳定。

## 13. 文档更新

需要更新：

```text
docs/data-ingestion.md
```

新增 Market Data Sync Jobs 一节，说明它与 `backtest data sync` 的区别。

```text
docs/cli.md
```

新增 `backtest data sync-job` 命令示例。

```text
docs/ai-handoff.md
```

补充：

- 当前分支新增的 data job 设计；
- 临时脚本能力已计划沉淀为 runner；
- 定时任务应该调用 `backtest data sync-job`；
- 大体积 `data/crypto` 和 `runs/crypto_market_data` 默认不提交。

## 14. 后续演进

第一版完成后，可以继续扩展：

- `--dry-run`：只展开 item 和 coverage，不实际拉取；
- `--start-date/--end-date` CLI 覆盖配置；
- `--output-dir` CLI 覆盖配置；
- 不可重试错误分类；
- exchange fallback；
- 数据质量检查；
- 增量刷新策略，例如默认拉最近 N 天；
- daemon 或 scheduler；
- A 股、港股、美股 provider 的批量任务配置示例。

## 15. 验收标准

本阶段完成后，应满足：

- 可以用一份 YAML 描述 4 个 crypto symbol、7 个 frequency 的批量同步任务；
- `backtest data sync-job --job ...` 能执行任务并复用现有缓存链路；
- 失败 item 可重试；
- 失败可以记录到 summary，并可选择继续剩余 item；
- 执行结束后生成 `summary.csv` 和 `summary.json`；
- 单元测试覆盖配置校验、runner 展开、重试、失败继续和 summary 输出；
- 文档和 `docs/ai-handoff.md` 说明后续 AI 如何继续开发和运行数据任务。
