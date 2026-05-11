from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


def build_strategy_results_catalog_payload(
    *,
    summary_frames: list[pd.DataFrame] | None = None,
    result_roots: list[Path] | None = None,
    chart_root: Path | None = None,
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for frame in summary_frames or []:
        records.extend(_summary_frame_to_records(frame))
    for root in result_roots or []:
        records.extend(_standard_result_root_to_records(Path(root), chart_root=chart_root))

    strategies = _group_records(records)
    return {
        "title": title or "Strategy Results",
        "generated_at": _now_iso(),
        "strategies": strategies,
        "summary": {
            "strategy_count": len(strategies),
            "result_count": sum(strategy["result_count"] for strategy in strategies),
        },
        "metadata": dict(metadata or {}),
    }


def write_strategy_results_catalog(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_strategy_results_catalog_html(payload), encoding="utf-8")


def render_strategy_results_catalog_html(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    safe_payload = payload_json.replace("</", "<\\/")
    return HTML_TEMPLATE.replace("__STRATEGY_RESULTS_CATALOG_PAYLOAD__", safe_payload)


def _summary_frame_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    records: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        result_id = _text(_pick(row, "case", "result_id", "project_name", "case_id"))
        if not result_id:
            continue
        signal_id = _int_or_none(_pick(row, "signal_id"))
        holding_days = _int_or_none(_pick(row, "holding_days"))
        explicit_case_id = _text(_pick(row, "case_id"))
        case_id = explicit_case_id or _runtime_case_id(signal_id, holding_days, result_id)
        legacy_report_href = _text(_pick(row, "report_path"))
        detail_href = f"strategy_account_viewer_{case_id}.html" if explicit_case_id or not legacy_report_href else ""
        raw_signal_slug = _text(_pick(row, "signal_slug", "strategy_slug"))
        slug = _strategy_slug(raw_signal_slug, result_id)
        strategy_id = _strategy_id(signal_id, raw_signal_slug, result_id, slug)
        records.append(
            {
                "result_id": result_id,
                "case_id": case_id,
                "strategy_id": strategy_id,
                "strategy_slug": slug,
                "strategy_name": _title_from_slug(slug),
                "source_type": "ten_buy_signal" if signal_id is not None or raw_signal_slug else "summary",
                "implementation": f"signal_slug:{raw_signal_slug}" if raw_signal_slug else "",
                "run_group": _text(_pick(row, "run_group")) or "summary",
                "holding_days": holding_days,
                "backend": _text(_pick(row, "backend")),
                "planning_mode": _text(_pick(row, "planning_mode")),
                "symbols": _int_or_none(_pick(row, "symbols", "signal_symbols")),
                "bars": _int_or_none(_pick(row, "bars")),
                "start_date": _text(_pick(row, "start_date", "first_signal_date")),
                "end_date": _text(_pick(row, "end_date", "last_signal_date")),
                "total_return": _float_or_none(_pick(row, "total_return")),
                "max_drawdown": _float_or_none(_pick(row, "max_drawdown")),
                "sharpe_ratio": _float_or_none(_pick(row, "sharpe_ratio")),
                "orders": _int_or_none(_pick(row, "orders")),
                "filled_orders": _int_or_none(_pick(row, "filled_orders")),
                "rejected_orders": _int_or_none(_pick(row, "rejected_orders")),
                "detail_href": detail_href,
                "legacy_report_href": legacy_report_href,
                "run_at": _text(_pick(row, "run_at", "created_at")),
            }
        )
    return records


def _standard_result_root_to_records(root: Path, *, chart_root: Path | None) -> list[dict[str, Any]]:
    roots = [root] if (root / "manifest.json").exists() else sorted(root.rglob("manifest.json"))
    records: list[dict[str, Any]] = []
    for manifest_path in roots:
        run_dir = manifest_path.parent if manifest_path.name == "manifest.json" else manifest_path
        manifest_file = run_dir / "manifest.json"
        metrics_file = run_dir / "metrics.json"
        if not manifest_file.exists() or not metrics_file.exists():
            continue
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        project_name = _text(manifest.get("project_name")) or run_dir.name
        slug = _strategy_slug("", project_name)
        strategy_id = _slugify(slug)
        report_path = run_dir / "report.html"
        records.append(
            {
                "result_id": run_dir.name,
                "case_id": run_dir.name,
                "strategy_id": strategy_id,
                "strategy_slug": slug,
                "strategy_name": project_name,
                "source_type": "standard_run",
                "implementation": _text(manifest.get("signal_source")),
                "run_group": str(run_dir.parent),
                "holding_days": None,
                "backend": "",
                "planning_mode": "",
                "symbols": len(manifest.get("symbols") or []),
                "bars": None,
                "start_date": _text(manifest.get("start_date")),
                "end_date": _text(manifest.get("end_date")),
                "total_return": _float_or_none(metrics.get("total_return")),
                "max_drawdown": _float_or_none(metrics.get("max_drawdown")),
                "sharpe_ratio": _float_or_none(metrics.get("sharpe_ratio")),
                "orders": None,
                "filled_orders": None,
                "rejected_orders": None,
                "detail_href": _detail_href_for_standard_run(run_dir, chart_root),
                "legacy_report_href": str(report_path) if report_path.exists() else "",
                "run_at": "",
            }
        )
    return records


def _group_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        groups.setdefault(record["strategy_id"], []).append(record)

    strategies: list[dict[str, Any]] = []
    for strategy_id, items in groups.items():
        sorted_items = sorted(
            items,
            key=lambda item: (
                item["holding_days"] if item["holding_days"] is not None else 10**9,
                item["case_id"],
            ),
        )
        returns = [item["total_return"] for item in sorted_items if item["total_return"] is not None]
        latest_run_at = max((item["run_at"] for item in sorted_items if item["run_at"]), default="")
        first = sorted_items[0]
        strategies.append(
            {
                "strategy_id": strategy_id,
                "name": first["strategy_name"],
                "slug": first["strategy_slug"],
                "source_type": first["source_type"],
                "implementation": first["implementation"],
                "result_count": len(sorted_items),
                "best_total_return": max(returns) if returns else None,
                "latest_run_at": latest_run_at,
                "results": [_result_record(item) for item in sorted_items],
            }
        )
    return sorted(strategies, key=lambda item: _natural_key(item["strategy_id"]))


def _result_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "result_id": record["result_id"],
        "case_id": record["case_id"],
        "strategy_id": record["strategy_id"],
        "run_group": record["run_group"],
        "holding_days": record["holding_days"],
        "backend": record["backend"],
        "planning_mode": record["planning_mode"],
        "symbols": record["symbols"],
        "bars": record["bars"],
        "start_date": record["start_date"],
        "end_date": record["end_date"],
        "total_return": record["total_return"],
        "max_drawdown": record["max_drawdown"],
        "sharpe_ratio": record["sharpe_ratio"],
        "orders": record["orders"],
        "filled_orders": record["filled_orders"],
        "rejected_orders": record["rejected_orders"],
        "detail_href": record["detail_href"],
        "legacy_report_href": record["legacy_report_href"],
    }


def _pick(row: pd.Series, *columns: str) -> Any:
    for column in columns:
        if column in row:
            value = row[column]
            if not _is_missing(value):
                return value
    return None


def _strategy_id(signal_id: int | None, raw_signal_slug: str, case_id: str, slug: str) -> str:
    if signal_id is not None:
        return f"signal_{signal_id:02d}"
    match = re.search(r"buy_signal_(\d+)", case_id)
    if match:
        return f"signal_{int(match.group(1)):02d}"
    match = re.match(r"^(\d+)[_-]", raw_signal_slug)
    if match:
        return f"signal_{int(match.group(1)):02d}"
    return _slugify(slug or case_id)


def _runtime_case_id(signal_id: int | None, holding_days: int | None, fallback: str) -> str:
    if signal_id is not None and holding_days is not None:
        return f"signal_{signal_id:02d}_hold_{holding_days}"
    return fallback


def _strategy_slug(raw_signal_slug: str, case_id: str) -> str:
    slug = raw_signal_slug.strip()
    if slug:
        return re.sub(r"^\d+[_-]", "", slug)
    match = re.match(r"buy_signal_\d+_(.+?)_hold_\d+$", case_id)
    if match:
        return match.group(1)
    return re.sub(r"_hold_\d+$", "", case_id)


def _title_from_slug(slug: str) -> str:
    return " ".join(part for part in slug.replace("-", "_").split("_") if part).title()


def _slugify(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower()).strip("_")
    return text or "strategy"


def _natural_key(value: str) -> list[Any]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def _detail_href_for_standard_run(run_dir: Path, chart_root: Path | None) -> str:
    if chart_root is None:
        return ""
    candidate = Path(chart_root) / f"strategy_account_viewer_{run_dir.name}.html"
    return candidate.name if candidate.exists() else ""


def _text(value: Any) -> str:
    if _is_missing(value):
        return ""
    return str(value)


def _float_or_none(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _int_or_none(value: Any) -> int | None:
    numeric = _float_or_none(value)
    if numeric is None:
        return None
    return int(numeric)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


HTML_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Strategy Results</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f7fb;
      --surface: #ffffff;
      --line: #d8e0e8;
      --line-soft: #edf1f5;
      --text: #1d2733;
      --muted: #667789;
      --blue: #1d5fd1;
      --green: #168a5a;
      --red: #c2412d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    }
    header {
      padding: 16px 20px 12px;
      background: var(--surface);
      border-bottom: 1px solid var(--line);
    }
    .topline {
      display: grid;
      grid-template-columns: minmax(260px, 1fr) auto;
      gap: 16px;
      align-items: start;
    }
    h1 {
      margin: 0;
      font-size: 22px;
      line-height: 1.2;
    }
    .subtitle {
      margin-top: 6px;
      color: var(--muted);
      font-size: 12px;
    }
    .header-actions {
      display: grid;
      justify-items: end;
      gap: 10px;
    }
    .home-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      padding: 0 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--blue);
      font-size: 13px;
      font-weight: 800;
      text-decoration: none;
      white-space: nowrap;
    }
    .home-link:hover {
      border-color: #b8c7d6;
      background: #f8fafc;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(3, minmax(120px, 1fr));
      gap: 1px;
      margin-top: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: var(--line);
      min-width: 360px;
    }
    .metric {
      background: var(--surface);
      padding: 9px 11px;
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
    }
    .metric strong {
      display: block;
      margin-top: 4px;
      font-size: 15px;
    }
    main {
      display: grid;
      grid-template-columns: minmax(260px, 360px) minmax(0, 1fr);
      gap: 14px;
      padding: 14px 20px 20px;
    }
    .panel {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      min-width: 0;
    }
    .panel-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
    }
    .panel-header h2 {
      margin: 0;
      font-size: 15px;
    }
    .search {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
    }
    input {
      width: 100%;
      height: 34px;
      padding: 0 10px;
      border: 1px solid var(--line);
      border-radius: 6px;
      font: inherit;
      font-size: 13px;
    }
    .strategy-list {
      display: grid;
      max-height: calc(100vh - 230px);
      overflow: auto;
    }
    .strategy-button {
      display: grid;
      gap: 5px;
      width: 100%;
      padding: 11px 14px;
      border: 0;
      border-bottom: 1px solid var(--line-soft);
      background: var(--surface);
      color: var(--text);
      font: inherit;
      text-align: left;
      cursor: pointer;
    }
    .strategy-button:hover,
    .strategy-button.active {
      background: #f8fafc;
    }
    .strategy-title {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      font-weight: 700;
      font-size: 13px;
    }
    .strategy-meta {
      color: var(--muted);
      font-size: 12px;
    }
    .result-meta {
      color: var(--muted);
      font-size: 12px;
    }
    .table-wrap {
      max-height: calc(100vh - 190px);
      overflow: auto;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }
    th, td {
      padding: 8px 9px;
      border-bottom: 1px solid var(--line-soft);
      text-align: right;
      white-space: nowrap;
    }
    th:first-child, td:first-child,
    th:nth-child(2), td:nth-child(2) {
      text-align: left;
    }
    th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: #f8fafc;
      color: var(--muted);
    }
    tr[data-detail-href] {
      cursor: pointer;
    }
    tr[data-detail-href]:hover td {
      background: #f8fafc;
    }
    .positive { color: var(--green); font-weight: 700; }
    .negative { color: var(--red); font-weight: 700; }
    .open-link {
      color: var(--blue);
      font-weight: 700;
      text-decoration: none;
    }
    .open-link[aria-disabled="true"] {
      color: var(--muted);
      pointer-events: none;
    }
    .empty {
      padding: 22px 14px;
      color: var(--muted);
      text-align: center;
    }
    @media (max-width: 900px) {
      .topline, main { grid-template-columns: 1fr; }
      .header-actions { justify-items: start; }
      .metrics { min-width: 0; }
      .strategy-list, .table-wrap { max-height: none; }
    }
    @media (max-width: 620px) {
      header, main { padding-left: 12px; padding-right: 12px; }
      .metrics { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <script id="strategy-results-catalog-payload" type="application/json">__STRATEGY_RESULTS_CATALOG_PAYLOAD__</script>
  <header>
    <div class="topline">
      <div>
        <h1 id="title">Strategy Results</h1>
        <div class="subtitle" id="subtitle"></div>
      </div>
      <div class="header-actions">
        <a class="home-link" id="workbenchHomeLink" href="#" hidden>Workbench Home</a>
        <section class="metrics" id="metrics"></section>
      </div>
    </div>
  </header>
  <main>
    <section class="panel">
      <div class="panel-header">
        <h2>Strategies</h2>
        <div class="result-meta" id="strategyCount"></div>
      </div>
      <div class="search">
        <input id="strategySearch" type="search" placeholder="Search strategy or case" autocomplete="off">
      </div>
      <div class="strategy-list" id="strategyList"></div>
    </section>
    <section class="panel">
      <div class="panel-header">
        <h2 id="resultsTitle">Backtest Results</h2>
        <div class="result-meta" id="resultsMeta"></div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Case</th>
              <th>Hold</th>
              <th>Return</th>
              <th>Max DD</th>
              <th>Sharpe</th>
              <th>Orders</th>
              <th>Rejected</th>
              <th>Backend</th>
              <th>Mode</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody id="resultRows"></tbody>
        </table>
      </div>
    </section>
  </main>
  <script>
    let payload = JSON.parse(document.getElementById("strategy-results-catalog-payload").textContent);
    const shellLinks = payload.links || {};
    let strategies = [];
    let summary = {};
    let selectedStrategyId = "";

    const escapeHtml = (value) => String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");

    const compact = (value) => {
      if (value === null || value === undefined || value === "") return "";
      const number = Number(value);
      if (!Number.isFinite(number)) return "";
      return number.toLocaleString(undefined, { maximumFractionDigits: 0 });
    };

    function formatPercent(value) {
      if (value === null || value === undefined || value === "") return "";
      const number = Number(value);
      if (!Number.isFinite(number)) return "";
      return `${(number * 100).toFixed(2)}%`;
    }

    function signedClass(value) {
      const number = Number(value);
      if (!Number.isFinite(number) || number === 0) return "";
      return number > 0 ? "positive" : "negative";
    }

    function strategyMatches(strategy, query) {
      if (!query) return true;
      const haystack = [
        strategy.strategy_id,
        strategy.name,
        strategy.slug,
        strategy.implementation,
        ...(strategy.results || []).map((result) => result.case_id)
      ].join(" ").toLowerCase();
      return haystack.includes(query);
    }

    function filteredStrategies() {
      const query = document.getElementById("strategySearch").value.trim().toLowerCase();
      return strategies.filter((strategy) => strategyMatches(strategy, query));
    }

    function renderHeader() {
      const workbenchHomeHref = payload.links?.workbench_home || payload.metadata?.workbench_home_href || "";
      const workbenchHomeLink = document.getElementById("workbenchHomeLink");
      if (workbenchHomeHref) {
        workbenchHomeLink.href = workbenchHomeHref;
        workbenchHomeLink.hidden = false;
      } else {
        workbenchHomeLink.hidden = true;
      }
      document.getElementById("title").textContent = payload.title || "Strategy Results";
      document.getElementById("subtitle").textContent = payload.generated_at
        ? `Generated ${payload.generated_at}`
        : "";
      document.getElementById("metrics").innerHTML = [
        ["Strategies", summary.strategy_count || strategies.length],
        ["Results", summary.result_count || strategies.reduce((total, item) => total + (item.result_count || 0), 0)],
        ["Selected", selectedStrategyId || "-"],
      ].map(([label, value]) => `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
    }

    function renderStrategies() {
      const items = filteredStrategies();
      if (!items.some((item) => item.strategy_id === selectedStrategyId)) {
        selectedStrategyId = items[0]?.strategy_id || "";
      }
      renderHeader();
      document.getElementById("strategyCount").textContent = `${items.length} / ${strategies.length}`;
      document.getElementById("strategyList").innerHTML = items.length ? items.map((strategy) => {
        const active = strategy.strategy_id === selectedStrategyId ? " active" : "";
        const best = formatPercent(strategy.best_total_return);
        return `<button class="strategy-button${active}" type="button" data-strategy-id="${escapeHtml(strategy.strategy_id)}">
          <span class="strategy-title">
            <span>${escapeHtml(strategy.strategy_id)} · ${escapeHtml(strategy.name || strategy.slug)}</span>
            <span>${escapeHtml(String(strategy.result_count || 0))}</span>
          </span>
          <span class="strategy-meta">${escapeHtml(strategy.slug || "")}${best ? ` | best ${escapeHtml(best)}` : ""}</span>
        </button>`;
      }).join("") : `<div class="empty">No strategies</div>`;
      renderResults();
    }

    function renderResults() {
      const strategy = strategies.find((item) => item.strategy_id === selectedStrategyId);
      document.getElementById("resultsTitle").textContent = strategy
        ? `${strategy.strategy_id} · ${strategy.name || strategy.slug}`
        : "Backtest Results";
      document.getElementById("resultsMeta").textContent = strategy ? `${strategy.result_count || 0} results` : "";
      const results = strategy?.results || [];
      document.getElementById("resultRows").innerHTML = results.length ? results.map((result) => {
        const href = result.detail_href || result.legacy_report_href || "";
        const disabled = href ? "" : ' aria-disabled="true"';
        const label = href ? "Open Result" : "Unavailable";
        const rowHref = href ? ` data-detail-href="${escapeHtml(href)}"` : "";
        return `<tr${rowHref}>
          <td>${escapeHtml(result.result_id || result.case_id || "")}</td>
          <td>${result.holding_days === null || result.holding_days === undefined ? "" : `${escapeHtml(result.holding_days)}d`}</td>
          <td class="${signedClass(result.total_return)}">${escapeHtml(formatPercent(result.total_return))}</td>
          <td class="${signedClass(result.max_drawdown)}">${escapeHtml(formatPercent(result.max_drawdown))}</td>
          <td>${result.sharpe_ratio === null || result.sharpe_ratio === undefined ? "" : Number(result.sharpe_ratio).toFixed(2)}</td>
          <td>${escapeHtml(compact(result.orders))}</td>
          <td>${escapeHtml(compact(result.rejected_orders))}</td>
          <td>${escapeHtml(result.backend || "")}</td>
          <td>${escapeHtml(result.planning_mode || "")}</td>
          <td><a class="open-link" href="${escapeHtml(href || "#")}"${disabled}>${label}</a></td>
        </tr>`;
      }).join("") : `<tr><td class="empty" colspan="10">No backtest results</td></tr>`;
    }

    function selectStrategy(strategyId) {
      selectedStrategyId = strategyId;
      renderStrategies();
    }

    async function loadPayload() {
      if (payload.mode === "dynamic") {
        document.getElementById("title").textContent = payload.title || "Strategy Results";
        document.getElementById("subtitle").textContent = "Loading strategy results";
        try {
          const response = await fetch("/api/strategy-results");
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
          }
          const apiPayload = await response.json();
          payload = {
            ...apiPayload,
            links: {
              ...shellLinks,
              ...(apiPayload.links || {}),
            },
          };
        } catch (error) {
          document.getElementById("subtitle").textContent = `Failed to load strategy results: ${error.message}`;
          document.getElementById("strategyList").innerHTML = `<div class="empty">No strategies</div>`;
          document.getElementById("resultRows").innerHTML = `<tr><td class="empty" colspan="10">No backtest results</td></tr>`;
          return;
        }
      }
      strategies = Array.isArray(payload.strategies) ? payload.strategies : [];
      summary = payload.summary || {};
      selectedStrategyId = strategies[0]?.strategy_id || "";
      renderHeader();
      renderStrategies();
    }

    document.getElementById("strategyList").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-strategy-id]");
      if (!button) return;
      selectStrategy(button.dataset.strategyId);
    });
    const resultRows = document.getElementById("resultRows");
    resultRows.addEventListener("click", (event) => {
      const row = event.target.closest("tr[data-detail-href]");
      if (!row) return;
      window.location.href = row.dataset.detailHref;
    });
    document.getElementById("strategySearch").addEventListener("input", renderStrategies);
    loadPayload();
  </script>
</body>
</html>
"""
