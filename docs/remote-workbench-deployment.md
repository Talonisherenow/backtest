# Remote Workbench Data Source Deployment

这份文档记录“VPS + Nginx + frp + 内网数据源机器”的远程数据源部署方式。目标是：

- 公网只访问 VPS 的 HTTPS 入口。
- 内网数据源机器不需要公网 IP，也不需要路由器端口转发。
- K-line 数据、crawl task、inventory、job submission 都在内网数据源机器执行。
- 外面的 workbench 通过 `--data-api-base-url` 切到这台远程数据源。

## Topology

```text
外部浏览器 / workbench
  -> https://data.example.com
  -> VPS Nginx
  -> 127.0.0.1:18768 on VPS
  -> frps
  -> frpc on source machine
  -> 127.0.0.1:8768 backtest data-source API
  -> 源端 parquet bars + sqlite metadata + crawl jobs
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

## Source Machine

源端机器的角色，由"哪台机器跑 frpc + `backtest data-source serve`"决定，frps
本身不限制是哪台机。当前内网数据源机器是一台 macOS Mac mini，下面 Linux 默认
路径仍可参考，macOS 特殊步骤见后文 [macOS (Mac mini) Setup](#macos-mac-mini-setup)。

在内网数据源机器启动 data-source API。它只监听本机环回地址，让 frpc 访问即可：

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

### macOS (Mac mini) Setup

一次性安装：

```bash
brew install uv frpc
# brew 在新版本上可能无法 symlink 完成，必要时手动：
ln -sf /usr/local/Cellar/uv/$(brew list --versions uv | awk '{print $2}')/bin/uv /usr/local/bin/uv
ln -sf /usr/local/Cellar/frpc/$(brew list --versions frpc | awk '{print $2}')/bin/frpc /usr/local/bin/frpc
```

项目依赖：

```bash
cd ~/code/backtest
UV_DEFAULT_INDEX=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple uv sync
```

如果内网数据源机器没有 crypto/bitget 数据，启动 `data-source serve` 时加
`--no-bitget`，否则会因 `data/crypto/bitget/bars` 不存在直接退出。

LaunchAgents 自启：把下面两份 plist 分别放到
`~/Library/LaunchAgents/com.backtest.data-source.plist` 和
`~/Library/LaunchAgents/com.backtest.frpc.plist`，然后：

```bash
launchctl load -w ~/Library/LaunchAgents/com.backtest.data-source.plist
launchctl load -w ~/Library/LaunchAgents/com.backtest.frpc.plist
launchctl list | grep backtest
tail -f /usr/local/var/log/backtest-data-source.err.log
tail -f /usr/local/var/log/frpc.log
```

`com.backtest.data-source.plist` 的关键字段：

```xml
<key>ProgramArguments</key>
<array>
    <string>/usr/local/bin/uv</string>
    <string>run</string>
    <string>--</string>
    <string>backtest</string>
    <string>data-source</string>
    <string>serve</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>8768</string>
    <string>--no-bitget</string>
</array>
<key>WorkingDirectory</key>
<string>/Users/&lt;you&gt;/code/backtest</string>
<key>EnvironmentVariables</key>
<dict>
    <key>BACKTEST_DATA_SOURCE_TOKEN</key>
    <string>CHANGE_ME_BACKTEST_API_TOKEN</string>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
</dict>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>/usr/local/var/log/backtest-data-source.out.log</string>
<key>StandardErrorPath</key><string>/usr/local/var/log/backtest-data-source.err.log</string>
```

`com.backtest.frpc.plist`：

```xml
<key>ProgramArguments</key>
<array>
    <string>/usr/local/bin/frpc</string>
    <string>-c</string>
    <string>/usr/local/etc/frp/frpc.toml</string>
</array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>/usr/local/var/log/frpc.out.log</string>
<key>StandardErrorPath</key><string>/usr/local/var/log/frpc.err.log</string>
```

只要 `LaunchAgents` 安装到位，重启 mac-mini 后 data-source 和 frpc 都会自动起，
公网入口立刻可用。

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

- `bindPort = 7000`（也可以直接绑 `443`，让 frpc 端口看起来像 HTTPS，省一个对外开放端口）
- `proxyBindAddr = "127.0.0.1"`
- `allowPorts = [{ single = 18768 }]`

`proxyBindAddr = "127.0.0.1"` 很重要：它让 frp 暴露出来的 `18768` 只在 VPS
本机可访问，公网只能走 Nginx 的 80/443。

当前 VPS（124.220.8.47）实际使用 `bindPort = 443`，配置文件在
`/etc/frp-frps.toml`，所以 frpc 端要写 `serverPort = 443`。

验证配置：

```bash
frps verify -c /etc/frp/frps.toml
```

VPS 防火墙只需要放行：

```text
22/tcp
80/tcp
443/tcp   # frps 绑在这里，且 Nginx 也可在此叠 SSL（看部署）
```

`7000/tcp` 在 frps 绑 443 的方案下不需要。不要放行 `18768/tcp`。

## Source frpc

样例配置在：

```text
deploy/frp/frpc.backtest-data-source.example.toml
```

复制到内网数据源机器：

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

如果 VPS 暂时还没绑域名/HTTPS，可以直接用裸 IP：

```bash
export BACKTEST_DATA_API_TOKEN="CHANGE_ME_BACKTEST_API_TOKEN"

uv run backtest chart serve-workbench \
  --results-root runs/ten_buy_signals/new_runtime_native_20260510 \
  --data-api-base-url http://124.220.8.47 \
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

远程提交 job 时，路径都是内网数据源机器上的路径，不是客户端机器上的路径：

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
- `/api/data/jobs` 会触发内网数据源机器执行 crawl job，只给自己的客户端 token。
