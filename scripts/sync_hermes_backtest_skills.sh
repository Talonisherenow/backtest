#!/usr/bin/env bash
set -euo pipefail

BACKTEST_REPO="${BACKTEST_REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)}"
BACKTEST_BRANCH="${BACKTEST_BRANCH:-$(git -C "$BACKTEST_REPO" branch --show-current 2>/dev/null || true)}"
BACKTEST_BRANCH="${BACKTEST_BRANCH:-feat/data-crawl-management}"
HERMES_ROOT="${HERMES_ROOT:-$HOME/.hermes}"
BACKTEST_HERMES_PROFILES="${BACKTEST_HERMES_PROFILES:-weixin-talon weixin-zf}"
BACKTEST_GIT_TIMEOUT_SECONDS="${BACKTEST_GIT_TIMEOUT_SECONDS:-45}"
export BACKTEST_REPO HERMES_ROOT BACKTEST_HERMES_PROFILES

if [[ ! -d "$BACKTEST_REPO/.git" ]]; then
  echo "backtest repo not found: $BACKTEST_REPO" >&2
  exit 2
fi

cd "$BACKTEST_REPO"
if [[ "${BACKTEST_SKIP_GIT_PULL:-0}" != "1" ]]; then
  export GIT_TERMINAL_PROMPT=0
  timeout "$BACKTEST_GIT_TIMEOUT_SECONDS" git fetch origin "$BACKTEST_BRANCH"
  current_branch="$(git branch --show-current || true)"
  if [[ "$current_branch" == "$BACKTEST_BRANCH" ]]; then
    timeout "$BACKTEST_GIT_TIMEOUT_SECONDS" git pull --ff-only origin "$BACKTEST_BRANCH"
  else
    timeout "$BACKTEST_GIT_TIMEOUT_SECONDS" git merge --ff-only "origin/$BACKTEST_BRANCH"
  fi
fi

python3 - <<'PY_SYNC'
from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

root = Path(os.environ.get("HERMES_ROOT", str(Path.home() / ".hermes"))).expanduser()
repo = Path(os.environ["BACKTEST_REPO"]).expanduser()
profiles = os.environ.get("BACKTEST_HERMES_PROFILES", "").split()
homes = [root] + [root / "profiles" / name for name in profiles]
src = repo / ".codex" / "skills" / "backtest-im-agent-api"

if not (src / "SKILL.md").exists():
    raise SystemExit(f"missing source skill: {src}")

soul = """# Hermes Agent Persona

You are Hermes Agent serving IM requests for the backtest project. Be concise, practical, and careful with operational boundaries.

## Backtest IM Agent Contract

These instructions are loaded fresh each message and apply to the default Hermes profile and configured IM profiles.

1. When the user mentions backtest market data, data-source, crawler service, crawl/fetch jobs, task status, inventory, K-line data, symbols, A-share, crypto, Bitget, Binance, or related Chinese phrases such as `爬虫`, `爬取`, `数据源`, `数据任务`, `行情`, `标的`, or `K线`, load `backtest-im-agent-api` with `skill_view(name="backtest-im-agent-api")` before answering.
2. For IM-side data-source work, use the configured backtest data-source HTTP API only. Do not run ad-hoc Python scripts, akshare scripts, ccxt scripts, shell crawlers, local database queries, repo modifications, git operations, SSH operations, Nginx/FRP edits, service restarts, or log inspection to satisfy user data/crawl requests.
3. Treat the data-source API as the source of truth. Use the narrowest relevant endpoint.
4. `POST /api/data/jobs` and `POST /api/data/retry-failed` require explicit user confirmation.
5. Use `BACKTEST_DATA_API_BASE_URL` and `BACKTEST_DATA_API_TOKEN` from the runtime environment or configured client. Never print bearer tokens or secrets.
6. If the user asks for operations work outside the IM boundary, say Hermes IM can do API-level checks only and hand off deployment/service changes to a data-source operator.

## Skill Refresh Contract

When code or project skills have changed, run `~/.hermes/bin/sync-backtest-skills` or this repo's `scripts/sync_hermes_backtest_skills.sh`, then run `/reload-skills` or restart the relevant gateway/profile process.
"""

stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
updated: list[str] = []

for home in homes:
    if not home.exists():
        continue
    target = home / "skills" / "software-development" / "backtest-im-agent-api"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, target, dirs_exist_ok=True)

    skill_md = target / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3 and "category:" not in parts[1]:
            parts[1] = parts[1].rstrip() + "\ncategory: software-development\n"
            text = "---".join(parts)
    skill_md.write_text(text, encoding="utf-8")

    (home / "SOUL.md").write_text(soul, encoding="utf-8")

    env_updates = {
        "BACKTEST_DATA_API_BASE_URL": os.environ.get("BACKTEST_DATA_API_BASE_URL", ""),
        "BACKTEST_DATA_API_TOKEN": os.environ.get("BACKTEST_DATA_API_TOKEN", ""),
    }
    if any(env_updates.values()):
        env_path = home / ".env"
        lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
        kept = [
            line
            for line in lines
            if not any(line.startswith(key + "=") for key in env_updates)
        ]
        if kept and kept[-1].strip():
            kept.append("")
        for key, value in env_updates.items():
            if value:
                kept.append(f"{key}={value}")
        env_path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    snapshot = home / ".skills_prompt_snapshot.json"
    if snapshot.exists():
        snapshot.unlink()
    (home / ".backtest_skill_sync").write_text(
        f"synced_at={stamp}\nrepo={repo}\nsource={src}\n",
        encoding="utf-8",
    )
    updated.append(str(target))

print("updated backtest-im-agent-api skills:")
for item in updated:
    print(f"- {item}")
print("next: run /reload-skills in active Hermes conversations or restart gateway/profile processes")
PY_SYNC
