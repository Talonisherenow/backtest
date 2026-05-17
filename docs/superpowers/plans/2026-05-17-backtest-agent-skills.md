# Backtest Agent Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create three role-specific project skills for data-source operations, workbench operations, and IM-agent data-source API usage.

**Architecture:** Keep each skill focused on one authority boundary. Store role-specific procedures in each skill's `SKILL.md`, move longer command/API details into local `references/` files, and remove the old broad `backtest-data-workbench` skill after the replacements exist.

**Tech Stack:** Codex project skills, Markdown `SKILL.md`, YAML frontmatter, `agents/openai.yaml`, existing backtest CLI and HTTP API documentation.

---

## File Structure

Create:

- `.codex/skills/backtest-data-source-ops/SKILL.md`
- `.codex/skills/backtest-data-source-ops/agents/openai.yaml`
- `.codex/skills/backtest-data-source-ops/references/deployment-runbook.md`
- `.codex/skills/backtest-data-source-ops/references/data-job-fields.md`
- `.codex/skills/backtest-workbench-ops/SKILL.md`
- `.codex/skills/backtest-workbench-ops/agents/openai.yaml`
- `.codex/skills/backtest-workbench-ops/references/workbench-runbook.md`
- `.codex/skills/backtest-im-agent-api/SKILL.md`
- `.codex/skills/backtest-im-agent-api/agents/openai.yaml`
- `.codex/skills/backtest-im-agent-api/references/access-discovery.md`
- `.codex/skills/backtest-im-agent-api/references/data-source-http-api.md`
- `.codex/skills/backtest-im-agent-api/references/dialogue-flows.md`

Delete:

- `.codex/skills/backtest-data-workbench/SKILL.md`
- `.codex/skills/backtest-data-workbench/agents/openai.yaml`

No Python runtime code changes are part of this plan.

## Task 1: Add Skill Validation Scenarios

**Files:**

- Create: `.codex/skills/backtest-data-source-ops/references/data-job-fields.md`
- Create: `.codex/skills/backtest-im-agent-api/references/access-discovery.md`
- Create: `.codex/skills/backtest-im-agent-api/references/dialogue-flows.md`

- [ ] **Step 1: Create the shared data job field reference**

Create `.codex/skills/backtest-data-source-ops/references/data-job-fields.md` with this content:

````markdown
# Data Job Fields

Use this reference when a user asks to get, fetch, download, crawl, sync, or backfill market data.

Before running or submitting a job, show a proposal that includes:

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

- date range: most recent one year ending on today's local date
- crypto: `source=ccxt`, `adjust=none`, `frequencies=[1d, 4h, 1h, 30m, 15m, 5m, 1m]`
- A-share: `source=akshare`, `adjust=qfq`, `frequencies=[1d]`

For crypto, confirm `exchange`. If the user did not name one, infer it only from an existing repo default or ask.

For A-share, do not use crypto intraday frequencies. AkShare currently accepts daily bars.
````

- [ ] **Step 2: Create the IM API access discovery reference**

Create `.codex/skills/backtest-im-agent-api/references/access-discovery.md` to require server-side IM agents to discover whether the current runtime can reach the backtest API before any read or write:

- reuse an injected runtime API client when available
- otherwise read `BACKTEST_DATA_API_BASE_URL` and `BACKTEST_DATA_API_TOKEN` from environment variables
- ask for configuration only if either value is still missing
- never print token values
- probe `GET /api/health` and `GET /api/data-sources`
- classify missing config, `401/403`, timeout, connection refused, `502/503/504`, and `404`
- stop before data reads or writes if the API is not reachable
- avoid assuming whether the path is Nginx, frp, direct networking, localhost forwarding, or another controlled route

- [ ] **Step 3: Create the IM dialogue validation reference**

Create `.codex/skills/backtest-im-agent-api/references/dialogue-flows.md` with this content:

````markdown
# IM Dialogue Flows

## Data Fetch

User intent examples: "拉数据", "补数据", "同步 BTC", "获取 A 股日线".

Flow:

1. Ensure an API client is configured. Run access discovery only if the client is missing, unvalidated, changed, or currently failing.
2. Identify market, symbols, source, exchange, date range, frequencies, adjust mode, and execution intent.
3. Fill defaults where safe.
4. Ask one concise follow-up if a required field remains ambiguous.
5. Show the final job payload summary.
6. Call `POST /api/data/jobs` only after the user confirms.
7. Return `job_id`, initial status, and the next status-check action.

## Retry Failed Tasks

Flow:

1. Ensure an API client is configured. Run access discovery only if the client is missing, unvalidated, changed, or currently failing.
2. Confirm `source_id`.
3. Show that retry will enqueue existing failed crawl tasks for that source.
4. Call `POST /api/data/retry-failed` only after confirmation.
5. Report queued count and task ids.

## Operations Requests

If the user asks to SSH, restart services, edit Nginx, edit frp, inspect logs, or change system service files, say the IM agent is limited to discovering and calling the data-source HTTP API from its current runtime. Offer API access discovery and read-only API checks instead.
````

- [ ] **Step 4: Verify references are discoverable**

Run:

```bash
rg -n "Data Job Fields|API Access Discovery|IM Dialogue Flows|POST /api/data/jobs|source=ccxt" .codex/skills
```

Expected: both new reference files appear in the output.

## Task 2: Create `backtest-data-source-ops`

**Files:**

- Create: `.codex/skills/backtest-data-source-ops/SKILL.md`
- Create: `.codex/skills/backtest-data-source-ops/agents/openai.yaml`
- Create: `.codex/skills/backtest-data-source-ops/references/deployment-runbook.md`

- [ ] **Step 1: Write `SKILL.md`**

Create `.codex/skills/backtest-data-source-ops/SKILL.md`:

````markdown
---
name: backtest-data-source-ops
description: Use when operating a backtest data-source machine or its VPS exposure, including data-source processes, frpc/frps, Nginx, crawl jobs, crawl task status, inventory, retries, ports, logs, and deployment verification.
---

# Backtest Data Source Ops

## Purpose

Operate the machine and infrastructure that owns cached market data, crawl tasks, and the public data-source API.

## First Checks

Confirm repo shape:

```bash
uv run backtest data-source serve --help
uv run backtest data sync-job --help
rg -n "data-source serve|frpc|frps|nginx|api/data/jobs" docs deploy .codex/skills
```

## Authority

Allowed:

- start and inspect `backtest data-source serve`
- inspect and maintain frpc/frps/Nginx deployment
- inspect logs, ports, and launch services
- submit, inspect, and retry crawl jobs after confirmation

Not the right skill for:

- local workbench UI setup; use `backtest-workbench-ops`
- IM-only API conversations; use `backtest-im-agent-api`

## Workflows

For deployment and process work, read `references/deployment-runbook.md`.

For data fetch, crawl, sync, backfill, retry, and job field confirmation, read `references/data-job-fields.md` before acting.

## Verification

Use the narrowest checks that match the user's request:

```bash
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" http://127.0.0.1:8768/api/health
curl -sS -H "Authorization: Bearer $BACKTEST_DATA_SOURCE_TOKEN" http://127.0.0.1:8768/api/data-sources
uv run backtest data tasks --metadata data/crypto/bitget/metadata.sqlite
uv run backtest data inventory --metadata data/crypto/bitget/metadata.sqlite
```

For public exposure, verify the chain in order: source loopback, VPS loopback, public HTTPS.
````

- [ ] **Step 2: Write deployment reference**

Create `.codex/skills/backtest-data-source-ops/references/deployment-runbook.md`:

````markdown
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
````

- [ ] **Step 3: Write UI metadata**

Create `.codex/skills/backtest-data-source-ops/agents/openai.yaml`:

```yaml
interface:
  display_name: "Backtest Data Source Ops"
  short_description: "Operate data-source services and jobs"
  default_prompt: "Use $backtest-data-source-ops to operate the backtest data-source service, deployment chain, crawl jobs, and task status."
```

- [ ] **Step 4: Verify trigger text**

Run:

```bash
rg -n "backtest-data-source-ops|data-source processes|frpc|frps|Nginx|crawl jobs" .codex/skills/backtest-data-source-ops
```

Expected: `SKILL.md`, `openai.yaml`, and `deployment-runbook.md` all appear where relevant.

## Task 3: Create `backtest-workbench-ops`

**Files:**

- Create: `.codex/skills/backtest-workbench-ops/SKILL.md`
- Create: `.codex/skills/backtest-workbench-ops/agents/openai.yaml`
- Create: `.codex/skills/backtest-workbench-ops/references/workbench-runbook.md`

- [ ] **Step 1: Write `SKILL.md`**

Create `.codex/skills/backtest-workbench-ops/SKILL.md`:

````markdown
---
name: backtest-workbench-ops
description: Use when configuring, starting, opening, or troubleshooting the backtest chart workbench, K-line viewer, strategy-results viewer, remote data API base URL, workbench token wiring, result roots, local ports, and browser verification.
---

# Backtest Workbench Ops

## Purpose

Operate the local workbench experience. The workbench may read K-line data from local bars or from a remote data-source API.

## First Checks

```bash
uv run backtest chart serve-workbench --help
rg -n "serve-workbench|data-api-base-url|BACKTEST_DATA_API_TOKEN" docs backtest .codex/skills
```

## Authority

Allowed:

- start and verify `backtest chart serve-workbench`
- configure `--data-api-base-url`
- configure `BACKTEST_DATA_API_TOKEN` or `--data-api-token`
- verify K-line and strategy-results pages

Not allowed:

- editing Nginx, frp, LaunchAgent, or system service files
- exposing local workbench publicly when the HTML includes a data API token

## Workflow

Read `references/workbench-runbook.md` for local and remote startup commands.

If the user asks to fix data-source deployment, route to `backtest-data-source-ops`.

If the user asks from an IM-agent context, route API-only actions to `backtest-im-agent-api`.
````

- [ ] **Step 2: Write workbench reference**

Create `.codex/skills/backtest-workbench-ops/references/workbench-runbook.md`:

````markdown
# Workbench Runbook

## Local Data

```bash
uv run backtest chart serve-workbench \
  --results-root runs/ten_buy_signals/new_runtime_native_20260510 \
  --a-share-bars-root data/bars \
  --bitget-bars-root data/crypto/bitget/bars \
  --host 127.0.0.1 \
  --port 8767
```

## Remote Data Source

```bash
export BACKTEST_DATA_API_TOKEN="..."
uv run backtest chart serve-workbench \
  --results-root runs/ten_buy_signals/new_runtime_native_20260510 \
  --data-api-base-url https://data.example.com \
  --host 127.0.0.1 \
  --port 8767
```

Open:

```text
http://127.0.0.1:8767/
http://127.0.0.1:8767/kline
http://127.0.0.1:8767/strategy-results
```

Useful probes:

```bash
curl -sS http://127.0.0.1:8767/api/strategy-results
curl -sS http://127.0.0.1:8767/api/manifest
```

Security note: do not publish this local workbench to the Internet when it embeds `data_api_token`.
````

- [ ] **Step 3: Write UI metadata**

Create `.codex/skills/backtest-workbench-ops/agents/openai.yaml`:

```yaml
interface:
  display_name: "Backtest Workbench Ops"
  short_description: "Start and verify the workbench"
  default_prompt: "Use $backtest-workbench-ops to start the chart workbench, connect it to a data-source API, and verify K-line and strategy result pages."
```

- [ ] **Step 4: Verify workbench trigger text**

Run:

```bash
rg -n "backtest-workbench-ops|serve-workbench|data-api-base-url|strategy-results|K-line" .codex/skills/backtest-workbench-ops
```

Expected: all terms appear in the new skill or its reference.

## Task 4: Create `backtest-im-agent-api`

**Files:**

- Create: `.codex/skills/backtest-im-agent-api/SKILL.md`
- Create: `.codex/skills/backtest-im-agent-api/agents/openai.yaml`
- Create: `.codex/skills/backtest-im-agent-api/references/data-source-http-api.md`

- [ ] **Step 1: Write `SKILL.md`**

Create `.codex/skills/backtest-im-agent-api/SKILL.md`:

```markdown
---
name: backtest-im-agent-api
description: Use when a server-side IM agent must answer backtest data-source requests by calling the data-source HTTP API, including health, sources, K-line data, crawl jobs, task status, inventory, and retry actions.
---

# Backtest IM Agent API

## Purpose

Support IM conversations by calling the backtest data-source HTTP API only.

## Hard Boundary

Never SSH, execute shell commands, edit Nginx, edit frp, inspect system logs, restart services, or read/write server files. If users ask for operations work, explain this boundary and offer API-level checks.

## Allowed API Surface

Read `references/data-source-http-api.md` before constructing requests.

Allowed without confirmation:

- `GET /api/health`
- `GET /api/data-sources`
- `GET /api/kline/manifest`
- `GET /api/kline/bars`
- `GET /api/data/tasks`
- `GET /api/data/inventory`
- `GET /api/data/jobs`
- `GET /api/data/jobs/<job_id>`

Allowed only after user confirmation:

- `POST /api/data/jobs`
- `POST /api/data/retry-failed`

## Conversation Flow

Read `references/dialogue-flows.md` when the user asks to fetch data, submit jobs, retry failures, or perform operations work.

Do not print bearer tokens. Report authorization failures without exposing token values.
```

- [ ] **Step 2: Write HTTP API reference**

Create `.codex/skills/backtest-im-agent-api/references/data-source-http-api.md`:

````markdown
# Data Source HTTP API

Base URL is configured by the server-side IM agent runtime.

All requests use:

```text
Authorization: Bearer <configured token>
```

Never print the token in chat.

## Read Endpoints

```text
GET /api/health
GET /api/data-sources
GET /api/kline/manifest
GET /api/kline/bars?source_id=<source_id>&symbol=<symbol>&frequency=<frequency>&adjust=<adjust>&limit=<n>&anchor=latest
GET /api/data/tasks?source_id=<source_id>
GET /api/data/inventory?source_id=<source_id>
GET /api/data/jobs
GET /api/data/jobs/<job_id>
```

## Submit Job

```text
POST /api/data/jobs
Content-Type: application/json
```

Body:

```json
{
  "name": "crypto-bitget-core",
  "source": "ccxt",
  "exchange": "bitget",
  "symbols": ["BTC/USDT", "ETH/USDT"],
  "frequencies": ["1d", "4h"],
  "adjust": "none",
  "start_date": "2025-05-17",
  "end_date": "2026-05-17",
  "bars_root": "data/crypto/bitget/bars",
  "metadata": "data/crypto/bitget/metadata.sqlite",
  "output_dir": "runs/crypto_market_data/bitget_core",
  "page_delay_seconds": 0.35,
  "retry": {
    "max_attempts": 5,
    "request_delay_seconds": 0.5,
    "failure_cooldown_seconds": 30,
    "continue_on_error": true
  }
}
```

Paths are server-side paths on the data-source machine.

## Retry Failed

```text
POST /api/data/retry-failed
Content-Type: application/json
```

Body:

```json
{"source_id":"bitget"}
```

## Status Meaning

Job status can be `submitted`, `running`, `success`, or `failed`.

Crawl task status can include `pending`, `running`, `retrying`, `success`, or `failed`.
````

- [ ] **Step 3: Write UI metadata**

Create `.codex/skills/backtest-im-agent-api/agents/openai.yaml`:

```yaml
interface:
  display_name: "Backtest IM Agent API"
  short_description: "Use data-source HTTP APIs from IM"
  default_prompt: "Use $backtest-im-agent-api to answer IM data requests through the backtest data-source HTTP API without doing server operations."
```

- [ ] **Step 4: Verify forbidden operations are explicit**

Run:

```bash
rg -n "Never SSH|Nginx|frp|POST /api/data/jobs|POST /api/data/retry-failed|confirmation" .codex/skills/backtest-im-agent-api
```

Expected: the hard boundary and write-confirmation rules appear.

## Task 5: Remove Old Broad Skill

**Files:**

- Delete: `.codex/skills/backtest-data-workbench/SKILL.md`
- Delete: `.codex/skills/backtest-data-workbench/agents/openai.yaml`

- [ ] **Step 1: Delete old skill files**

Delete both old broad skill files. The three role-specific skills replace it:

- `backtest-data-source-ops`
- `backtest-workbench-ops`
- `backtest-im-agent-api`

- [ ] **Step 2: Verify old skill is absent**

Run:

```bash
test ! -e .codex/skills/backtest-data-workbench/SKILL.md
test ! -e .codex/skills/backtest-data-workbench/agents/openai.yaml
```

Expected: both commands exit 0.

## Task 6: Cross-Skill Discovery Review

**Files:**

- Review all files under `.codex/skills/backtest-data-source-ops`
- Review all files under `.codex/skills/backtest-workbench-ops`
- Review all files under `.codex/skills/backtest-im-agent-api`

- [ ] **Step 1: Check skill frontmatter**

Run:

```bash
for file in .codex/skills/*/SKILL.md; do
  printf '%s\n' "$file"
  sed -n '1,8p' "$file"
done
```

Expected: each skill has `name` and `description` frontmatter.

- [ ] **Step 2: Check trigger separation**

Run:

```bash
rg -n "description: Use when" .codex/skills/*/SKILL.md
```

Expected:

- `backtest-data-source-ops` mentions process, deployment, jobs, task status, inventory, logs, ports
- `backtest-workbench-ops` mentions workbench, K-line viewer, strategy-results, data API base URL, browser verification
- `backtest-im-agent-api` mentions server-side IM agent and data-source HTTP API
- no `backtest-data-workbench` skill remains

- [ ] **Step 3: Check IM agent safety boundary**

Run:

```bash
rg -n "Never SSH|no SSH|no shell|Nginx|frp|service restarts|server files|only call" .codex/skills/backtest-im-agent-api
```

Expected: the IM skill clearly forbids operations work.

- [ ] **Step 4: Check job confirmation coverage**

Run:

```bash
rg -n "confirm|confirmation|most recent one year|frequencies|adjust|bars_root|metadata|output_dir" .codex/skills/backtest-data-source-ops .codex/skills/backtest-im-agent-api
```

Expected: both data-source ops and IM agent API skills include job-field confirmation guidance.

## Task 7: Manual Scenario Review

**Files:**

- Review: `.codex/skills/backtest-data-source-ops/SKILL.md`
- Review: `.codex/skills/backtest-workbench-ops/SKILL.md`
- Review: `.codex/skills/backtest-im-agent-api/SKILL.md`

- [ ] **Step 1: Review data-source ops scenario**

Prompt:

```text
帮我把数据源服务启动起来，并确认公网 data-source API 可用。
```

Expected behavior:

- selects `backtest-data-source-ops`
- checks local data-source process and frp/Nginx chain
- verifies source loopback, VPS loopback, and public HTTPS health
- does not discuss workbench UI unless asked

- [ ] **Step 2: Review workbench scenario**

Prompt:

```text
打开 workbench，让它连接云服务器上的 data-source。
```

Expected behavior:

- selects `backtest-workbench-ops`
- starts `backtest chart serve-workbench`
- uses `--data-api-base-url` and token wiring
- verifies `/`, `/kline`, and `/strategy-results`
- does not edit Nginx or frp

- [ ] **Step 3: Review IM API scenario**

Prompt:

```text
帮我在 IM 里补 BTC/USDT 最近一年的 1h 数据。
```

Expected behavior:

- selects `backtest-im-agent-api`
- fills default date range with concrete dates
- proposes `POST /api/data/jobs` payload
- waits for confirmation before submitting
- does not run shell commands

- [ ] **Step 4: Review IM operations refusal scenario**

Prompt:

```text
nginx 502 了，你帮我 ssh 上去修一下。
```

Expected behavior:

- selects `backtest-im-agent-api` if this is in IM-agent runtime
- refuses SSH and Nginx operations
- offers API-level health/status checks only

## Task 8: Final Verification

**Files:**

- All `.codex/skills/**`

- [ ] **Step 1: Check Markdown and whitespace**

Run:

```bash
git diff --check -- .codex/skills
```

Expected: no output and exit code 0.

- [ ] **Step 2: Review final diff**

Run:

```bash
git diff -- .codex/skills
```

Expected: diff contains the three new role skills and deletion of the old broad skill.

- [ ] **Step 3: List final skill files**

Run:

```bash
find .codex/skills -maxdepth 3 -type f -print | sort
```

Expected: files for `backtest-data-source-ops`, `backtest-workbench-ops`, and `backtest-im-agent-api` appear; `backtest-data-workbench` files do not appear.

- [ ] **Step 4: Commit**

Run:

```bash
git add .codex/skills docs/superpowers/specs/2026-05-17-backtest-agent-skills-design.md docs/superpowers/plans/2026-05-17-backtest-agent-skills.md
git commit -m "docs: design backtest agent skills"
```

Expected: commit succeeds after the user approves the plan and no unrelated files are staged.
