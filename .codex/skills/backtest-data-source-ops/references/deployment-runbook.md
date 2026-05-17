# Data Source Deployment Runbook

Primary docs:

- `docs/remote-workbench-deployment.md`
- `docs/local-data-source-migration-runbook.zh.md`
- `deploy/frp/frps.backtest-data-source.example.toml`
- `deploy/frp/frpc.backtest-data-source.example.toml`
- `deploy/nginx/backtest-data-source.example.conf`

## Exposure Model

The required contract is: an authorized client on the target server can reach the home/local `backtest data-source` HTTP API through a configured `base_url`.

Common topology:

```text
server-side agent/client -> VPS entrypoint -> forwarding path -> source 127.0.0.1:8768 -> backtest data-source API
```

The forwarding path may include Nginx, frps/frpc, localhost binding, or another controlled route. Do not make the IM/API skill depend on a specific transport; make the endpoint discoverable and verify it with API probes.

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

Public or server-runtime probe:

```bash
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" "$BACKTEST_DATA_SOURCE_BASE_URL/api/health"
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" "$BACKTEST_DATA_SOURCE_BASE_URL/api/data-sources"
```

Give IM agents only the API `base_url` and data-source API token they need. Do not give them SSH, frp, Nginx, or service-management authority.
