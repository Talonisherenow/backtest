# Backtest Agent Skills Design

Date: 2026-05-17
Status: draft for review

## 1. Goal

Split the current broad backtest skill into three role-oriented project skills so different agents operate with the right authority boundary:

- data-source operators manage local and remote runtime infrastructure
- workbench operators configure and verify the user-facing local workbench
- IM agents only call the data-source HTTP API and never perform operations work

The design keeps the project skills small enough to load quickly, while preserving enough domain context for Cursor, Codex, and server-side agents to make safe decisions.

## 2. Current Project Context

The repository already has the core capabilities needed by these skills:

- data-source HTTP service: `backtest data-source serve`
- data-source API implementation: `backtest/data_source/server.py` and `backtest/data_source/api.py`
- local workbench service: `backtest chart serve-workbench`
- remote workbench data API options: `--data-api-base-url` and `--data-api-token`
- remote deployment notes: `docs/remote-workbench-deployment.md`
- market-data operations notes: `docs/market-data-operations.md`
- previous broad project skill: `.codex/skills/backtest-data-workbench` (removed after role-specific replacements were created)

The current skill mixes data crawling, process operation, deployment, and viewer usage. That is convenient for one local assistant, but unsafe for a server-side IM agent because it blurs "call the API" and "operate the server".

## 3. Skill Split

### 3.1 `backtest-data-source-ops`

Use this skill when an AI assistant is operating on the data-source machine or on infrastructure that exposes that data source.

Responsibilities:

- manage `backtest data-source serve`
- manage local data-source process launch mode, including macOS LaunchAgent or equivalent service setup
- manage `frpc` on the data-source machine
- inspect or maintain VPS `frps` and Nginx configuration for the backtest data-source public entrypoint
- verify local, tunnel, and public data-source health
- prepare, confirm, submit, inspect, and retry crawl jobs
- inspect crawl task state and inventory through CLI or HTTP API
- diagnose logs, ports, stale processes, token mismatch, missing bars roots, and metadata path mistakes

Non-responsibilities:

- do not manage workbench UI behavior except to verify that the data-source API is reachable
- do not act as the IM conversation policy layer
- do not expose `backtest data-source serve` or frp `remotePort` directly to the public Internet

Primary references:

- `docs/remote-workbench-deployment.md`
- `docs/market-data-operations.md`
- `configs/data_jobs/crypto_bitget_core.yaml`
- `deploy/frp/frps.backtest-data-source.example.toml`
- `deploy/frp/frpc.backtest-data-source.example.toml`
- `deploy/nginx/backtest-data-source.example.conf`

### 3.2 `backtest-workbench-ops`

Use this skill when an AI assistant is configuring, starting, validating, or troubleshooting the local workbench experience.

Responsibilities:

- start `backtest chart serve-workbench`
- configure local or remote K-line data through `--data-api-base-url`
- pass the data-source token through `--data-api-token` or `BACKTEST_DATA_API_TOKEN`
- configure strategy result roots
- select local bars roots when no remote data-source API is used
- verify `/`, `/kline`, `/strategy-results`, and relevant same-origin JSON endpoints
- diagnose workbench failures caused by wrong token, unreachable data API, bad source id, missing result root, or port conflict

Non-responsibilities:

- do not edit Nginx, frp, LaunchAgent, or system service files
- do not submit crawl jobs unless explicitly acting through a documented data-source API workflow
- do not publish the local workbench to the public Internet, because the HTML payload may contain the data API token

Primary references:

- `backtest/cli/chart.py`
- `backtest/charts/workbench_server.py`
- `docs/remote-workbench-deployment.md`
- `docs/market-data-operations.md`

### 3.3 `backtest-im-agent-api`

Use this skill only for a server-side IM conversation agent that talks to users and calls the backtest data-source HTTP API.

Responsibilities:

- discover whether the current server runtime can reach a configured backtest data-source API
- classify missing endpoint, missing token, authorization failure, wrong base URL, and unreachable forwarding path
- understand the data-source HTTP API contract
- collect missing user intent fields in conversation
- confirm write operations before calling them
- submit crawl jobs through `POST /api/data/jobs`
- retry failed tasks through `POST /api/data/retry-failed`
- inspect health, sources, K-line manifest, bars, tasks, inventory, and jobs
- report asynchronous job progress using job status and crawl task status

Hard boundary:

- no SSH
- no shell commands
- no Nginx edits
- no frp edits
- no systemd or LaunchAgent actions
- no service restarts
- no reading or writing server files
- no using client-local paths as server paths
- no token disclosure in chat

Allowed endpoints:

```text
GET  /api/health
GET  /api/data-sources
GET  /api/kline/manifest
GET  /api/kline/bars
GET  /api/data/tasks?source_id=<source_id>
GET  /api/data/inventory?source_id=<source_id>
GET  /api/data/jobs
GET  /api/data/jobs/<job_id>
POST /api/data/jobs
POST /api/data/retry-failed
```

Write endpoints require explicit user confirmation after the agent has shown the final request fields.

The IM agent must not assume the API is exposed specifically through Nginx or frp. Those are deployment details owned by the data-source ops skill. The IM agent works from a configured API client or discovered `base_url` plus bearer token. It should prefer `BACKTEST_DATA_API_BASE_URL` and `BACKTEST_DATA_API_TOKEN` from environment variables when no API client is injected. It should probe `GET /api/health` and `GET /api/data-sources` only when establishing access, diagnosing a failure, or answering an explicit connectivity question; normal data operations should call the narrowest relevant endpoint directly.

## 4. Shared Behavioral Rules

### 4.1 Data Job Field Confirmation

Whenever a user asks to get, fetch, download, crawl, sync, or backfill market data, the responsible skill must produce a job-field proposal before running or submitting anything.

Required fields:

- market or asset class
- symbols or symbol source
- source
- exchange when `source=ccxt`
- concrete `start_date` and `end_date`
- frequencies
- adjust mode
- server-side `bars_root`
- server-side `metadata`
- server-side `output_dir`
- whether the operation will only prepare config or actually execute

Defaults:

- date range defaults to the most recent one year ending on today's local date
- crypto defaults to `source=ccxt`, `adjust=none`, and frequencies `[1d, 4h, 1h, 30m, 15m, 5m, 1m]`
- A-share defaults to `source=akshare`, `adjust=qfq`, and frequencies `[1d]`

### 4.2 Authority Boundary

The data-source ops skill may operate processes and deployment files.

The workbench ops skill may start and verify the local workbench, but should route deployment problems to the data-source ops skill.

The IM agent API skill may only use configured HTTP API access and run access discovery when needed from its current runtime. If an IM user asks it to fix deployment, restart services, edit Nginx, inspect logs, or SSH into a server, it should say that those actions are outside its authority and offer API-level checks it can run.

### 4.3 Token Handling

Skills must treat `FRP_TOKEN`, `BACKTEST_DATA_SOURCE_TOKEN`, and `BACKTEST_DATA_API_TOKEN` as separate values.

Agents should never print bearer tokens back to chat. They may state whether a token is configured, missing, rejected, or required.

IM agents should receive the data-source API token through `BACKTEST_DATA_API_TOKEN` or their runtime secret/config channel. If the token or base URL is absent, the skill should ask for configuration rather than guessing. It must not request frp tokens or server SSH credentials. `BACKTEST_DATA_SOURCE_TOKEN` is a data-source service variable and should only be used by an IM agent if that runtime explicitly documents it as a client compatibility alias.

## 5. Proposed Skill File Layout

```text
.codex/skills/
  backtest-data-source-ops/
    SKILL.md
    agents/openai.yaml
    references/deployment-runbook.md
    references/data-job-fields.md
  backtest-workbench-ops/
    SKILL.md
    agents/openai.yaml
    references/workbench-runbook.md
  backtest-im-agent-api/
    SKILL.md
    agents/openai.yaml
    references/data-source-http-api.md
    references/dialogue-flows.md
```

The old `.codex/skills/backtest-data-workbench` skill is removed once the three replacements exist. Keeping a compatibility router would add discovery ambiguity and could cause future agents to load a broad skill instead of the correct role-specific one.

## 6. Validation Scenarios

The final skills should be reviewed against these scenarios:

1. "帮我把数据源服务启动起来，并确认公网 data-source API 可用。"
   Expected skill: `backtest-data-source-ops`.

2. "帮我拉 BTC/USDT 和 ETH/USDT 最近一年的 1h 和 1d 数据。"
   Expected skill: `backtest-data-source-ops` or `backtest-im-agent-api`, depending on runtime. Both must confirm job fields before execution.

3. "打开 workbench，让它连接云服务器上的 data-source。"
   Expected skill: `backtest-workbench-ops`.

4. "IM 里帮我看看 bitget 还有哪些失败任务。"
   Expected skill: `backtest-im-agent-api`; discover API access, then use only HTTP API.

5. "IM 里帮我重启 nginx 修一下 502。"
   Expected skill: `backtest-im-agent-api`; refuse operations work and offer API access discovery and health checks only.

6. "IM 服务器现在能不能连到我家里的 backtest 后台？"
   Expected skill: `backtest-im-agent-api`; probe configured `base_url` with token using `GET /api/health` and `GET /api/data-sources`, then report reachability without assuming transport topology.

7. "workbench 的 K-line 页面 401。"
   Expected skill: `backtest-workbench-ops`; diagnose token wiring and remote API authorization.

## 7. Rollout Strategy

First create the new skills and references. Then remove the old broad skill so future agents choose one of the role-specific skills directly.

Do not change runtime code as part of this skill split. If later validation reveals an API gap, create a separate code design and plan for that gap.
