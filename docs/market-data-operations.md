# Market Data Operations

这份文档面向日常使用：不依赖 AI，也不需要记住实现细节。当前主要覆盖加密货币
CCXT 数据任务和本地 K 线 viewer。

## Quick Start

在项目根目录执行：

```bash
uv run backtest data sync-job --job configs/data_jobs/crypto_bitget_core.yaml
```

启动本地 viewer：

```bash
./scripts/start_crypto_viewer.sh
```

打开地址：

```text
http://127.0.0.1:8765/
```

如果需要在公网通过 VPS + Nginx + frp 访问家里服务器上的 data-source API，并让
外部 workbench 通过 `--data-api-base-url` 切换数据源，见
[`remote-workbench-deployment.md`](remote-workbench-deployment.md)。

如果没有使用 `uv`，先安装项目：

```bash
python -m pip install -e ".[dev]"
```

之后可以把上面的 `uv run backtest ...` 换成 `backtest ...`。一键 viewer
脚本也支持这个模式：它会优先使用 `uv run backtest`，找不到 `uv` 时使用已安装的
`backtest` 命令。

## Data Job Config

当前示例任务是：

```text
configs/data_jobs/crypto_bitget_core.yaml
```

它会抓取 Bitget spot OHLCV：

```text
symbols: BTC/USDT, ETH/USDT, SOL/USDT, BNB/USDT
frequencies: 1d, 4h, 1h, 30m, 15m, 5m, 1m
date range: 2023-05-09 to 2026-05-08
bars_root: data/crypto/bitget/bars
metadata: data/crypto/bitget/metadata.sqlite
output_dir: runs/crypto_market_data/bitget_core
page_delay_seconds: 0.35
```

常改字段：

- `symbols`: 要抓取的交易对。
- `frequencies`: 要抓取的 K 线周期。
- `start_date` / `end_date`: 目标数据范围。
- `exchange`: CCXT 交易所 id，例如 `bitget`、`binance`。
- `bars_root`: Parquet K 线落盘目录。建议按交易所隔离。
- `metadata`: SQLite 任务和 catalog 元数据。建议按交易所隔离。
- `output_dir`: 本次 job 的 summary 输出目录。
- `page_delay_seconds`: 翻页请求间隔，用于降低触发限流的概率。
- `retry`: 单个 job item 的重试策略。

## Submit A Crawl Job

前台运行，适合临时补数据：

```bash
uv run backtest data sync-job --job configs/data_jobs/crypto_bitget_core.yaml
```

后台运行，适合长任务：

```bash
mkdir -p runs/crypto_market_data/bitget_core
nohup uv run backtest data sync-job \
  --job configs/data_jobs/crypto_bitget_core.yaml \
  > runs/crypto_market_data/bitget_core/backfill.log 2>&1 &
echo $! > runs/crypto_market_data/bitget_core/backfill.pid
```

停止后台任务：

```bash
kill "$(cat runs/crypto_market_data/bitget_core/backfill.pid)"
```

再次运行同一个 job 是安全的：catalog 会按 `symbol + frequency + adjust +
source` 判断缺口，已经覆盖的数据不会重复抓取。

## Check Progress

看进程是否还在：

```bash
ps -p "$(cat runs/crypto_market_data/bitget_core/backfill.pid)"
```

看日志：

```bash
tail -f runs/crypto_market_data/bitget_core/backfill.log
```

看 crawl task 状态：

```bash
uv run backtest data tasks --metadata data/crypto/bitget/metadata.sqlite
```

看已写入的数据 catalog：

```bash
uv run backtest data inventory --metadata data/crypto/bitget/metadata.sqlite
```

任务结束后看汇总：

```bash
open runs/crypto_market_data/bitget_core/summary.csv
```

也可以直接查看 JSON：

```bash
cat runs/crypto_market_data/bitget_core/summary.json
```

`summary.csv` / `summary.json` 在 job 退出时写入。长任务运行中，主要用
`tasks`、`inventory`、日志和进程状态判断进度。

## Task Lifecycle

`backtest data sync-job` 会把 `symbols x frequencies` 展开成多个 job item。
每个 item 会调用同一套数据同步链路：

1. 查询 source-aware catalog，判断缺失范围。
2. 为缺失范围创建 crawl task。
3. 把 task 标记为 `running`。
4. 从 provider 抓取 bars。
5. 写入 Parquet 分区。
6. 更新 catalog 覆盖范围。
7. 标记 task 为 `success` 或 `failed`。

当前 task 状态：

```text
pending
running
success
failed
retrying
```

当前没有 pause/cancel 命令；停止后台任务需要用系统进程管理命令，例如 `kill`。

## Retry Failed Tasks

先查看失败任务：

```bash
uv run backtest data tasks --metadata data/crypto/bitget/metadata.sqlite
```

把 failed task 标记为 retrying：

```bash
uv run backtest data retry --failed --metadata data/crypto/bitget/metadata.sqlite
```

然后重新运行同一个 job：

```bash
uv run backtest data sync-job --job configs/data_jobs/crypto_bitget_core.yaml
```

下一次匹配的 sync 会优先执行 `retrying` task，再计算新的缺口。

## Start The Viewer

推荐直接使用脚本：

```bash
./scripts/start_crypto_viewer.sh
```

默认参数：

```text
bars root: data/crypto
adjust: none
host: 127.0.0.1
port: 8765
window size: 5000
```

脚本会启动动态 viewer，并在 macOS 上自动打开：

```text
http://127.0.0.1:8765/
```

如果端口已经有 viewer 在运行，脚本会探测 `/api/manifest`，确认是 K-line viewer
后直接打开已有页面并退出。如果端口被其他服务占用，脚本会提示换端口。

可以通过环境变量覆盖默认值：

```bash
BACKTEST_VIEWER_PORT=8766 \
BACKTEST_VIEWER_WINDOW_SIZE=1000 \
./scripts/start_crypto_viewer.sh
```

等价的手动命令是：

```bash
uv run backtest chart serve \
  --bars-root data/crypto \
  --adjust none \
  --host 127.0.0.1 \
  --port 8765 \
  --window-size 5000
```

`data/crypto` 会自动识别下面这种多 source 目录：

```text
data/crypto/
  bitget/bars/
  binance/bars/
```

在页面里可以通过 `Data Status` 切换数据源。切换后，主页面只展示该数据源下的
symbol 和 frequency。

动态 viewer 的时间窗口行为：

- `Jump to` 输入框始终显示当前可见窗口第一根 K 线的开始时间。
- 输入一个不在 K 线边界上的时间时，会定位到包含该时间的那根 K 线。例如 `5m`
  周期输入 `10:02` 会展示 `10:00` 开始的窗口。
- 切换 frequency 或 window size 时，会继续以当前 `Jump to` 时间为基准。
- 如果目标时间之后不足一个 window，就展示最后一个完整 window，并把 `Jump to`
  自动更新为实际窗口第一根 K 线时间。

## Static Viewer

如果要生成一个可以用 `file://` 打开的静态 HTML：

```bash
uv run backtest chart viewer \
  --bars-root data/crypto/bitget/bars \
  --output runs/charts/crypto_kline_viewer.html \
  --limit 5000 \
  --adjust none
```

静态 HTML 会把选中的 bars 嵌入文件。`--limit 0` 会嵌入全部数据，但文件会很大。

## Remote LAN Data Source API

在数据机器上启动 K-line 数据 API：

```bash
uv run backtest data-source serve --host 0.0.0.0 --port 8768
```

在本机启动 workbench，并让 K-line viewer 读取远端数据 API：

```bash
uv run backtest chart serve-workbench --data-api-base-url http://SERVER_IP:8768 --host 127.0.0.1 --port 8767
```

探测远端服务：

```bash
curl http://SERVER_IP:8768/api/health
curl http://SERVER_IP:8768/api/kline/manifest
```

## Scheduling

定时任务建议直接调用 `sync-job`。例如 cron：

```cron
0 8 * * * cd /Users/Tyrone.Shi/code-private/backtest && uv run backtest data sync-job --job configs/data_jobs/crypto_bitget_core.yaml >> runs/crypto_market_data/bitget_core/cron.log 2>&1
```

注意：

- 定时任务里要 `cd` 到项目根目录。
- 每个交易所建议独立 `bars_root` 和 `metadata`。
- 多次运行同一个 job 会自动跳过已覆盖区间，只补缺口。
- 如果交易所限流，调大 `page_delay_seconds` 或 retry cooldown。

## Data Source Scheduled Jobs

如果已经运行 `backtest data-source serve`，也可以通过 data-source HTTP API
管理内置定时任务。它不会创建新的爬取链路；到点后会复用现有
`POST /api/data/jobs` 提交数据爬取任务。

查看后端支持的 schedule 字段、source 默认值和示例：

```bash
curl -sS http://127.0.0.1:8768/api/data/schedule-options \
  -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN"
```

创建一个默认关闭的 schedule：

```bash
curl -sS http://127.0.0.1:8768/api/data/schedules \
  -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "bitget-hourly",
    "trigger": {
      "type": "interval",
      "every": 1,
      "unit": "hours",
      "start_at": "2026-05-20T09:00:00+08:00",
      "timezone": "Asia/Shanghai"
    },
    "repeat": {"mode": "count", "count": 24},
    "job": {
      "source_id": "bitget",
      "symbols": ["BTC/USDT", "ETH/USDT"],
      "frequencies": ["1h"],
      "date_range": {"type": "last_n_days", "days": 7}
    },
    "overlap_policy": "skip"
  }'
```

`start_at` 可用于 `interval`、`daily`、`weekly`，表示最早开始执行的具体时间点。
对 `daily` / `weekly` 来说，第一次执行会落到 `start_at` 之后的第一个匹配本地墙钟时间。

确认无误后开启：

```bash
curl -sS -X POST http://127.0.0.1:8768/api/data/schedules/<schedule_id>/enable \
  -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN"
```

其他常用操作：

```bash
curl -sS http://127.0.0.1:8768/api/data/schedules \
  -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN"

curl -sS -X POST http://127.0.0.1:8768/api/data/schedules/<schedule_id>/disable \
  -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN"

curl -sS -X POST http://127.0.0.1:8768/api/data/schedules/<schedule_id>/run-now \
  -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN"

curl -sS http://127.0.0.1:8768/api/data/schedules/<schedule_id>/runs \
  -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN"
```
