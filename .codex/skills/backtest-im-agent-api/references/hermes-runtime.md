# Hermes Runtime Setup

Use this reference when configuring a Hermes Agent server or refreshing the
server-side IM profiles after backtest code or project skills change.

## Contract

Hermes IM profiles must load `backtest-im-agent-api` for backtest market-data
requests and must use the backtest data-source HTTP API instead of local
crawler scripts or server operations.

## Required Runtime Variables

Each active Hermes home/profile should have these variables available to the
gateway process:

```text
BACKTEST_DATA_API_BASE_URL=<server-reachable data-source API origin>
BACKTEST_DATA_API_TOKEN=<bearer token>
```

For the VPS + frp deployment, the server-side base URL is usually the VPS
loopback route:

```text
http://127.0.0.1:18768
```

Do not commit tokens. Put secrets in `~/.hermes/.env` and profile `.env` files
or the host runtime secret channel.

## Sync Script

From the repo root, install or refresh Hermes skills with:

```bash
BACKTEST_DATA_API_BASE_URL=http://127.0.0.1:18768 \
BACKTEST_DATA_API_TOKEN=... \
scripts/sync_hermes_backtest_skills.sh
```

Defaults:

- `BACKTEST_REPO`: current repo root
- `BACKTEST_BRANCH`: current git branch, falling back to
  `feat/data-crawl-management`
- `HERMES_ROOT`: `~/.hermes`
- `BACKTEST_HERMES_PROFILES`: `weixin-talon weixin-zf`
- `BACKTEST_GIT_TIMEOUT_SECONDS`: `45`

The script:

1. Optionally fast-forwards the repo from origin.
2. Copies `.codex/skills/backtest-im-agent-api` into default Hermes and each
   configured profile under `skills/software-development/`.
3. Ensures Hermes-compatible `category: software-development` frontmatter.
4. Writes a `SOUL.md` contract that forces data/crawler requests through the
   API-only skill.
5. Updates `.env` with API variables only when the variables are provided.
6. Removes `.skills_prompt_snapshot.json` so the next Hermes turn rebuilds the
   skill index.

After running the script, run `/reload-skills` in active Hermes conversations
or restart the relevant gateway/profile processes.
