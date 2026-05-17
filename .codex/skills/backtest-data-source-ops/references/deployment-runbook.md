# Data Source Deployment Runbook

Primary docs:

- `docs/remote-workbench-deployment.md`
- `docs/local-data-source-migration-runbook.zh.md`
- `deploy/frp/frps.backtest-data-source.example.toml`
- `deploy/frp/frpc.backtest-data-source.example.toml`
- `deploy/nginx/backtest-data-source.example.conf`

## Process Chain

```text
public client -> VPS Nginx -> VPS 127.0.0.1:18768 -> frps -> frpc -> source 127.0.0.1:8768 -> backtest data-source API
```

## Source Machine

Start local API:

```bash
export BACKTEST_DATA_SOURCE_TOKEN="..."
uv run backtest data-source serve --host 127.0.0.1 --port 8768
```

Probe:

```bash
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" http://127.0.0.1:8768/api/health
```

## VPS

Important invariants:

- frp `proxyBindAddr` must stay `127.0.0.1`
- public firewall should not expose `18768/tcp`
- Nginx should be the only public HTTP(S) entrypoint
- `FRP_TOKEN` and `BACKTEST_DATA_SOURCE_TOKEN` are different secrets

Probe on VPS:

```bash
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" http://127.0.0.1:18768/api/health
sudo nginx -t
```

Public probe:

```bash
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" https://data.example.com/api/health
```
