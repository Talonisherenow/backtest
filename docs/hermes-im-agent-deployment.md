# Hermes IM Agent Deployment

This project keeps the server-side Hermes Agent contract in the repo so the IM
side can be refreshed after code or skill changes.

## Goal

Hermes IM agents answer backtest data-source requests through the HTTP API only.
They should not run one-off crawler scripts, direct `akshare`/`ccxt` snippets,
SQLite queries, SSH operations, service restarts, Nginx/FRP edits, or repo
changes for ordinary IM requests.

## Runtime Inputs

Configure each Hermes home/profile with:

```bash
BACKTEST_DATA_API_BASE_URL=http://127.0.0.1:18768
BACKTEST_DATA_API_TOKEN=...
```

`BACKTEST_DATA_API_BASE_URL` is the origin reachable from the Hermes server.
For the VPS + frp deployment, `http://127.0.0.1:18768` routes through frp to the
home data-source service. Do not commit token values.

## Refresh After Project Updates

From the repo on the Hermes server:

```bash
BACKTEST_DATA_API_BASE_URL=http://127.0.0.1:18768 \
BACKTEST_DATA_API_TOKEN=... \
scripts/sync_hermes_backtest_skills.sh
```

The script syncs `.codex/skills/backtest-im-agent-api` into:

- `~/.hermes/skills/software-development/backtest-im-agent-api`
- `~/.hermes/profiles/weixin-talon/skills/software-development/backtest-im-agent-api`
- `~/.hermes/profiles/weixin-zf/skills/software-development/backtest-im-agent-api`

It also writes the shared `SOUL.md` IM contract, updates `.env` when API
variables are provided, removes stale `.skills_prompt_snapshot.json`, and records
`.backtest_skill_sync`.

If GitHub fetch is temporarily slow, use the current checkout:

```bash
BACKTEST_SKIP_GIT_PULL=1 scripts/sync_hermes_backtest_skills.sh
```

## Activate New Context

After syncing:

1. Run `/reload-skills` in active Hermes conversations, or restart the gateway
   profile processes.
2. Confirm both IM profiles are running with the API variables in their process
   environment.
3. Probe from the Hermes server:

```bash
set -a
. ~/.hermes/profiles/weixin-talon/.env
set +a
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_API_TOKEN" \
  "$BACKTEST_DATA_API_BASE_URL/api/health"
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_API_TOKEN" \
  "$BACKTEST_DATA_API_BASE_URL/api/data-sources"
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_API_TOKEN" \
  "$BACKTEST_DATA_API_BASE_URL/api/data/tasks/summary?source_id=bitget"
```

Expected result: all three return HTTP 200 JSON.

## Skill Contract

The repo source of truth is `.codex/skills/backtest-im-agent-api`.

When users mention crawler service, crawl jobs, data tasks, K-line data,
A-share, crypto, Bitget, Binance, or Chinese trigger words such as `爬虫`,
`爬取`, `数据源`, `数据任务`, `行情`, `标的`, or `K线`, Hermes must load
`backtest-im-agent-api` and call the data-source HTTP API.
