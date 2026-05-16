# 本地数据源机器迁移操作手册

这份文档记录如何把当前本地 data-source / workbench 运行方式迁移到另一台本地机器。目标是：新机器拉下仓库后，按这里的命令就能启动本地数据源、验证接口，并让本地或公网 workbench 指向它。

## 1. 当前这台机器的停机记录

本次已经在当前机器上停止了这些 backtest 相关进程：

- `com.backtest.workbench` LaunchAgent，对应本地 workbench `127.0.0.1:8767`。
- `com.backtest.frpc` LaunchAgent，旧 frp 隧道。
- `com.backtest.data-source-tunnel` LaunchAgent，旧 SSH 反向隧道。
- `backtest data-source serve`，旧本机数据源 `0.0.0.0:8768`。
- 临时 `ssh -R 127.0.0.1:18768:127.0.0.1:8768` 隧道进程。

如果之后需要再次确认当前机器已经停干净，可以运行：

```bash
pgrep -af "backtest chart serve-workbench|backtest data-source serve|frpc|ssh .*18768:127.0.0.1:8768|sshpass .*18768" || true
lsof -nP -iTCP:8767 -sTCP:LISTEN || true
lsof -nP -iTCP:8768 -sTCP:LISTEN || true
```

期望结果：没有 workbench/data-source/tunnel 进程，`8767` 和 `8768` 没有监听。

## 2. 新机器准备仓库

在新的本地数据源机器上拉代码并安装依赖：

```bash
git clone https://github.com/Talonisherenow/backtest.git
cd backtest
git checkout feat/data-crawl-management

python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[dev]"
```

如果机器上已经有 `uv`，也可以使用 `uv run backtest ...`，但本文统一使用 `.venv/bin/backtest`，减少环境差异。

## 3. 复制数据

代码仓库不包含本地缓存数据，迁移时需要单独复制。当前最关键的是 Bitget crypto 数据：

```text
data/crypto/bitget/bars/
data/crypto/bitget/metadata.sqlite
```

从旧源端机器往新机器复制的示例：

```bash
rsync -az data/crypto/bitget/ <NEW_USER>@<NEW_SOURCE_IP>:/path/to/backtest/data/crypto/bitget/
```

如果还需要 A 股数据，也复制：

```text
data/bars/
data/metadata.sqlite
data/universe/
```

复制后在新机器上检查：

```bash
du -sh data/crypto/bitget
find data/crypto/bitget/bars -type f | wc -l
ls -lh data/crypto/bitget/metadata.sqlite
```

## 4. 启动数据源

只使用 crypto/Bitget 数据时，推荐先关闭 A 股数据源，避免缺少 A 股目录导致混淆：

```bash
.venv/bin/backtest data-source serve \
  --bitget-bars-root data/crypto/bitget/bars \
  --bitget-metadata data/crypto/bitget/metadata.sqlite \
  --no-a-share \
  --host 0.0.0.0 \
  --port 8768
```

本机验证：

```bash
curl -sS http://127.0.0.1:8768/api/health
curl -sS http://127.0.0.1:8768/api/data-sources
curl -sS http://127.0.0.1:8768/api/kline/manifest | head -c 500
```

如果要在局域网另一台电脑访问，把 `<NEW_SOURCE_IP>` 换成新机器局域网 IP：

```bash
curl -sS http://<NEW_SOURCE_IP>:8768/api/health
```

## 5. 启动本地 workbench

如果 workbench 和数据源在同一台新机器：

```bash
.venv/bin/backtest chart serve-workbench \
  --data-api-base-url http://127.0.0.1:8768 \
  --host 127.0.0.1 \
  --port 8767
```

打开：

```text
http://127.0.0.1:8767/
http://127.0.0.1:8767/kline
```

如果 workbench 在另一台电脑，指向新数据源机器：

```bash
.venv/bin/backtest chart serve-workbench \
  --data-api-base-url http://<NEW_SOURCE_IP>:8768 \
  --host 127.0.0.1 \
  --port 8767
```

## 6. 可选：配置为 macOS 常驻服务

如果新数据源机器也是 macOS，可以用 LaunchAgent 常驻启动。下面是 data-source 模板，把路径中的用户名和仓库目录改成新机器实际路径：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.backtest.data-source</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/backtest/.venv/bin/backtest</string>
    <string>data-source</string>
    <string>serve</string>
    <string>--bitget-bars-root</string>
    <string>data/crypto/bitget/bars</string>
    <string>--bitget-metadata</string>
    <string>data/crypto/bitget/metadata.sqlite</string>
    <string>--no-a-share</string>
    <string>--host</string>
    <string>0.0.0.0</string>
    <string>--port</string>
    <string>8768</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>WorkingDirectory</key>
  <string>/path/to/backtest</string>
  <key>StandardOutPath</key>
  <string>/path/to/backtest/runs/workbench/data-source.log</string>
  <key>StandardErrorPath</key>
  <string>/path/to/backtest/runs/workbench/data-source.err</string>
</dict>
</plist>
```

安装示例：

```bash
mkdir -p ~/Library/LaunchAgents runs/workbench
cp com.backtest.data-source.plist ~/Library/LaunchAgents/
plutil -lint ~/Library/LaunchAgents/com.backtest.data-source.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.backtest.data-source.plist
launchctl kickstart -k "gui/$(id -u)/com.backtest.data-source"
launchctl print "gui/$(id -u)/com.backtest.data-source"
```

停止：

```bash
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/com.backtest.data-source.plist
```

## 7. 如果要接公网 workbench

公网 workbench 只需要填数据源 base URL，例如：

```text
http://<PUBLIC_DATA_SOURCE_HOST>
```

但公网入口必须满足：

- `GET /api/health` 返回 `200` JSON。
- `GET /api/data-sources` 返回 `200` JSON。
- `GET /api/kline/manifest` 返回 `200` JSON。
- 响应里只出现一组 `Access-Control-Allow-Origin`，不要 Nginx 和后端重复加 CORS。

检查命令：

```bash
curl -sS -D - -o /tmp/health.out \
  -H "Origin: http://127.0.0.1:8767" \
  http://<PUBLIC_DATA_SOURCE_HOST>/api/health

cat /tmp/health.out
```

如果使用 Nginx 反代，而后端已经加了 CORS，Nginx 里应隐藏上游 CORS 头再统一添加：

```nginx
proxy_hide_header Access-Control-Allow-Origin;
proxy_hide_header Access-Control-Allow-Methods;
proxy_hide_header Access-Control-Allow-Headers;
proxy_hide_header Access-Control-Max-Age;

add_header Access-Control-Allow-Origin "*" always;
add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
add_header Access-Control-Allow-Headers "Content-Type, Authorization" always;
```

## 8. 本次调试记录摘要

- 旧 VPS `45.32.248.231` 曾配置过 Nginx + frp，后来发现本地数据源机器到 VPS 的 frp 控制连接不稳定，会出现 `timeout trying to get work connection`，外部表现为 `502`。
- 临时测试过 SSH 反向隧道 `-R 127.0.0.1:18768:127.0.0.1:8768`，链路可建立，但跨公网实时回源仍容易慢响应，不适合作为交互式 workbench 的长期方案。
- 新公网地址 `http://124.220.8.47` 已被配置进本地 workbench，但当时 `/api/health`、`/api/data-sources`、`/api/kline/manifest` 返回 `Empty reply from server`，说明新服务器侧还需要启动或修正 data-source HTTP 服务。
- 当前这台机器已停止本地 workbench、data-source 和隧道，迁移时建议在新数据源机器直接运行 data-source，再让 workbench 指向新机器或公网反代地址。
