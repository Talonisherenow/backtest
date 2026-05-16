# Remote Workbench Data Source Deployment

这份文档记录“VPS + Nginx + frp + 家里服务器”的远程数据源部署方式。目标是：

- 公网只访问 VPS 的 HTTPS 入口。
- 家里服务器不需要公网 IP，也不需要路由器端口转发。
- K-line 数据、crawl task、inventory、job submission 都在家里服务器执行。
- 外面的 workbench 通过 `--data-api-base-url` 切到这台远程数据源。

## Topology

```text
外部浏览器 / workbench
  -> https://data.example.com
  -> VPS Nginx
  -> 127.0.0.1:18768 on VPS
  -> frps
  -> frpc on home server
  -> 127.0.0.1:8768 backtest data-source API
  -> 家里 parquet bars + sqlite metadata + crawl jobs
```

frp 负责内网穿透，Nginx 负责公网 HTTPS 入口。`backtest data-source serve`
自己负责 bearer token 鉴权。

## Tokens

需要两类 token，建议分别生成：

```bash
openssl rand -hex 32
```

- `FRP_TOKEN`: frpc 连接 frps 用，只保护隧道控制面。
- `BACKTEST_DATA_SOURCE_TOKEN`: data-source API 的 bearer token，保护 HTTP API。

不要把这两个 token 设成一样。

## Home Server

在家里服务器启动 data-source API。它只监听本机环回地址，让 frpc 访问即可：

```bash
export BACKTEST_DATA_SOURCE_TOKEN="CHANGE_ME_BACKTEST_API_TOKEN"

uv run backtest data-source serve \
  --host 127.0.0.1 \
  --port 8768 \
  --api-token "$BACKTEST_DATA_SOURCE_TOKEN"
```

也可以只设置环境变量，省略命令行 token：

```bash
export BACKTEST_DATA_SOURCE_TOKEN="CHANGE_ME_BACKTEST_API_TOKEN"

uv run backtest data-source serve \
  --host 127.0.0.1 \
  --port 8768
```

本机验证：

```bash
curl -sS \
  -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" \
  http://127.0.0.1:8768/api/health
```

未带 token 应该返回 `401`。

## VPS frps

样例配置在：

```text
deploy/frp/frps.backtest-data-source.example.toml
```

复制到 VPS：

```bash
sudo install -m 600 deploy/frp/frps.backtest-data-source.example.toml /etc/frp/frps.toml
sudo vim /etc/frp/frps.toml
```

必须改：

- `auth.token`

建议保留：

- `bindPort = 7000`
- `proxyBindAddr = "127.0.0.1"`
- `allowPorts = [{ single = 18768 }]`

`proxyBindAddr = "127.0.0.1"` 很重要：它让 frp 暴露出来的 `18768` 只在 VPS
本机可访问，公网只能走 Nginx 的 80/443。

验证配置：

```bash
frps verify -c /etc/frp/frps.toml
```

VPS 防火墙只需要放行：

```text
22/tcp
80/tcp
443/tcp
7000/tcp
```

不要放行 `18768/tcp`。

## Home frpc

样例配置在：

```text
deploy/frp/frpc.backtest-data-source.example.toml
```

复制到家里服务器：

```bash
sudo install -m 600 deploy/frp/frpc.backtest-data-source.example.toml /etc/frp/frpc.toml
sudo vim /etc/frp/frpc.toml
```

必须改：

- `serverAddr`
- `auth.token`

验证配置：

```bash
frpc verify -c /etc/frp/frpc.toml
```

启动 frpc 后，在 VPS 上验证 frp 隧道：

```bash
curl -sS \
  -H "Authorization: Bearer CHANGE_ME_BACKTEST_API_TOKEN" \
  http://127.0.0.1:18768/api/health
```

## VPS Nginx

样例配置在：

```text
deploy/nginx/backtest-data-source.example.conf
```

复制到 VPS，并把 `data.example.com` 和证书路径换成自己的：

```bash
sudo install -m 644 deploy/nginx/backtest-data-source.example.conf \
  /etc/nginx/conf.d/backtest-data-source.conf
sudo nginx -t
sudo systemctl reload nginx
```

公网验证：

```bash
curl -sS \
  -H "Authorization: Bearer CHANGE_ME_BACKTEST_API_TOKEN" \
  https://data.example.com/api/health
```

## Workbench Client

在任意外部机器启动 workbench，切到 VPS 的远程数据源：

```bash
export BACKTEST_DATA_API_TOKEN="CHANGE_ME_BACKTEST_API_TOKEN"

uv run backtest chart serve-workbench \
  --results-root runs/ten_buy_signals/new_runtime_native_20260510 \
  --data-api-base-url https://data.example.com \
  --host 127.0.0.1 \
  --port 8767
```

打开：

```text
http://127.0.0.1:8767/kline
```

`BACKTEST_DATA_API_TOKEN` 会被写进本地 workbench HTML payload，浏览器请求远程
data-source API 时会自动带：

```text
Authorization: Bearer <token>
```

因此不要把这个本地 workbench 再公开给别人访问。公网入口应该公开 data-source
API，workbench 建议在自己的电脑上启动。

## Submit Data Jobs Remotely

远程提交 job 时，路径都是家里服务器上的路径，不是客户端机器上的路径：

```bash
curl -sS https://data.example.com/api/data/jobs \
  -H "Authorization: Bearer CHANGE_ME_BACKTEST_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "crypto-bitget-core",
    "source": "ccxt",
    "exchange": "bitget",
    "symbols": ["BTC/USDT", "ETH/USDT"],
    "frequencies": ["1d", "4h"],
    "adjust": "none",
    "start_date": "2025-01-01",
    "end_date": "2025-01-31",
    "bars_root": "data/crypto/bitget/bars",
    "metadata": "data/crypto/bitget/metadata.sqlite",
    "output_dir": "runs/crypto_market_data/bitget_core"
  }'
```

查看 job：

```bash
curl -sS \
  -H "Authorization: Bearer CHANGE_ME_BACKTEST_API_TOKEN" \
  https://data.example.com/api/data/jobs
```

查看 task：

```bash
curl -sS \
  -H "Authorization: Bearer CHANGE_ME_BACKTEST_API_TOKEN" \
  "https://data.example.com/api/data/tasks?source_id=bitget"
```

重试失败 task：

```bash
curl -sS https://data.example.com/api/data/retry-failed \
  -H "Authorization: Bearer CHANGE_ME_BACKTEST_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source_id":"bitget"}'
```

## Security Notes

- 不要裸露 `backtest data-source serve` 到公网。
- 不要让 frp 的 `remotePort` 直接公网可达；用 `proxyBindAddr = "127.0.0.1"` 让
  Nginx 成为唯一公网入口。
- Nginx 层可以继续叠加 Basic Auth、IP allowlist 或 mTLS。
- API token 是项目层最后一道门；即使 Nginx 配错，未带 bearer token 的请求也会被拒绝。
- `/api/data/jobs` 会触发家里服务器执行 crawl job，只给自己的客户端 token。
