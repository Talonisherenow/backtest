from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.core.symbols import normalize_symbol, safe_symbol_path, symbol_from_safe_path

BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]
METADATA_COLUMNS = ["code", "name", "exchange", "board", "industry"]
FREQUENCY_ORDER = {
    "1m": 10,
    "5m": 20,
    "15m": 30,
    "30m": 40,
    "1h": 50,
    "60m": 50,
    "4h": 60,
    "1d": 70,
}


def build_kline_payload(
    bars_root: Path,
    universe_path: Path | None = None,
    symbols: list[str] | None = None,
    limit: int = 300,
    frequency: str | None = "1d",
    frequencies: list[str] | None = None,
    adjust: str = "qfq",
    source_roots: list[tuple[str, Path]] | None = None,
) -> dict[str, Any]:
    if limit < 0:
        raise ValueError("limit must be non-negative")

    normalized_symbols = [normalize_symbol(symbol) for symbol in symbols] if symbols else None
    metadata = _read_universe_metadata(universe_path)
    roots = source_roots or [("default", bars_root)]

    sources = []
    for source_id, source_root in roots:
        source_id = _normalize_source_id(source_id)
        selected_frequencies = _resolve_frequencies(source_root, frequency, frequencies, adjust)
        requested_symbols = normalized_symbols or _discover_symbols(
            source_root, selected_frequencies, adjust
        )
        items = _build_source_symbols(
            source_root,
            requested_symbols,
            selected_frequencies,
            adjust,
            limit,
            metadata,
        )
        if not items:
            continue
        sources.append(
            {
                "source_id": source_id,
                "source_label": _source_label(source_id),
                "frequency": selected_frequencies[0]
                if len(selected_frequencies) == 1
                else "multi",
                "frequencies": selected_frequencies,
                "symbols": sorted(items, key=lambda item: item["symbol"]),
            }
        )

    if not sources:
        raise ValueError("No cached K-line data found for the requested symbols")

    primary = sources[0]
    all_frequencies = _sort_frequencies(
        [frequency for source in sources for frequency in source["frequencies"]]
    )
    return {
        "source_id": primary["source_id"],
        "source_label": primary["source_label"],
        "frequency": primary["frequency"],
        "frequencies": all_frequencies,
        "adjust": adjust,
        "limit": limit,
        "symbols": primary["symbols"],
        "sources": sources,
    }


def write_kline_viewer(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_kline_viewer_html(payload), encoding="utf-8")


def render_kline_viewer_html(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    safe_payload = payload_json.replace("</", "<\\/")
    return _viewer_template().replace("__KLINE_PAYLOAD__", safe_payload)


def _viewer_template() -> str:
    template_path = Path(__file__).with_name("kline_viewer_template.html")
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    return HTML_TEMPLATE


def _resolve_frequencies(
    bars_root: Path,
    frequency: str | None,
    frequencies: list[str] | None,
    adjust: str,
) -> list[str]:
    if frequencies:
        return list(dict.fromkeys(frequencies))
    if frequency:
        return [frequency]
    return _discover_frequencies(bars_root, adjust)


def _discover_frequencies(bars_root: Path, adjust: str) -> list[str]:
    frequencies = []
    for path in bars_root.glob("frequency=*"):
        if not path.is_dir():
            continue
        if (path / f"adjust={adjust}").exists():
            frequencies.append(path.name.removeprefix("frequency="))
    return _sort_frequencies(frequencies)


def _sort_frequencies(frequencies: list[str]) -> list[str]:
    return sorted(set(frequencies), key=lambda value: (FREQUENCY_ORDER.get(value, 999), value))


def _build_source_symbols(
    bars_root: Path,
    requested_symbols: list[str],
    selected_frequencies: list[str],
    adjust: str,
    limit: int,
    metadata: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    items = []
    for symbol in requested_symbols:
        series = []
        for current_frequency in selected_frequencies:
            entry = _read_symbol_series(bars_root, symbol, current_frequency, adjust, limit)
            if entry is not None:
                series.append(entry)
        if not series:
            continue
        details = metadata.get(symbol, {})
        items.append(
            {
                "symbol": symbol,
                "code": details.get("code", _symbol_code(symbol)),
                "name": details.get("name", ""),
                "exchange": _metadata_text(details, "exchange", _symbol_exchange(symbol)),
                "board": _metadata_text(details, "board", _symbol_board(symbol)),
                "industry": details.get("industry", ""),
                "bars": series[0]["bars"],
                "series": series,
            }
        )
    return items


def _discover_symbols(bars_root: Path, frequencies: list[str], adjust: str) -> list[str]:
    symbols = []
    for frequency in frequencies:
        base = bars_root / f"frequency={frequency}" / f"adjust={adjust}"
        if not base.exists():
            continue
        for path in base.glob("symbol=*"):
            if path.is_dir():
                symbols.append(symbol_from_safe_path(path.name.removeprefix("symbol=")))
    return sorted(set(symbols))


def _read_universe_metadata(universe_path: Path | None) -> dict[str, dict[str, str]]:
    if universe_path is None:
        return {}
    frame = pd.read_csv(universe_path, dtype={"symbol": str, "code": str})
    if "symbol" not in frame.columns:
        raise ValueError("universe CSV must contain a symbol column")

    metadata: dict[str, dict[str, str]] = {}
    for _, row in frame.iterrows():
        symbol = normalize_symbol(str(row["symbol"]))
        metadata[symbol] = {
            column: _clean_text(row[column]) if column in frame.columns else ""
            for column in METADATA_COLUMNS
        }
    return metadata


def _read_symbol_series(
    bars_root: Path,
    symbol: str,
    frequency: str,
    adjust: str,
    limit: int,
) -> dict[str, Any] | None:
    symbol_root = (
        bars_root
        / f"frequency={frequency}"
        / f"adjust={adjust}"
        / f"symbol={safe_symbol_path(symbol)}"
    )
    paths = sorted(symbol_root.glob("year=*/bars.parquet"))
    if not paths:
        return None

    frame = pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)
    if frame.empty:
        return None

    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").drop_duplicates(["date", "symbol"], keep="last")
    limited = frame if limit == 0 else frame.tail(limit)
    return {
        "frequency": frequency,
        "adjust": adjust,
        "rows": int(len(frame)),
        "loaded_rows": int(len(limited)),
        "first_bar": _timestamp_label(frame["date"].iloc[0], frequency),
        "last_bar": _timestamp_label(frame["date"].iloc[-1], frequency),
        "years": _years_from_paths(paths),
        "bars": [_bar_to_json(row, frequency) for _, row in limited[BAR_COLUMNS].iterrows()],
    }


def _bar_to_json(row: pd.Series, frequency: str) -> dict[str, Any]:
    return {
        "date": _timestamp_label(row["date"], frequency),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]),
        "amount": float(row["amount"]),
    }


def _clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value)


def _timestamp_label(value: object, frequency: str) -> str:
    timestamp = pd.Timestamp(value)
    if frequency == "1d":
        return timestamp.date().isoformat()
    return timestamp.to_pydatetime().isoformat(timespec="seconds")


def _years_from_paths(paths: list[Path]) -> list[int]:
    years = []
    for path in paths:
        raw_year = path.parent.name.removeprefix("year=")
        if raw_year.isdigit():
            years.append(int(raw_year))
    return sorted(set(years))


def _symbol_code(symbol: str) -> str:
    if "." in symbol:
        return symbol.split(".")[0]
    return symbol


def _symbol_exchange(symbol: str) -> str:
    if "." in symbol:
        return symbol.split(".")[1]
    if "/" in symbol:
        return "Crypto"
    return ""


def _symbol_board(symbol: str) -> str:
    if "/" in symbol:
        return "Spot"
    return ""


def _metadata_text(details: dict[str, str], key: str, default: str) -> str:
    value = details.get(key, "")
    return value if value else default


def _normalize_source_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("source id must not be empty")
    return normalized


def _source_label(source_id: str) -> str:
    if source_id == "default":
        return "Cache"
    return source_id.replace("_", " ").replace("-", " ").title()


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>K-line Cache Viewer</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f8fa;
      --surface: #ffffff;
      --line: #dbe2e8;
      --text: #1f2933;
      --muted: #687782;
      --red: #d32f2f;
      --green: #00897b;
      --blue: #1565c0;
      --amber: #f9a825;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
    }
    .topbar {
      display: block;
      padding: 16px 20px 12px;
      background: var(--surface);
      border-bottom: 1px solid var(--line);
    }
    .topbar-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 16px;
    }
    .title-block {
      min-width: 0;
    }
    h1 {
      margin: 0;
      font-size: 20px;
      line-height: 1.2;
      font-weight: 700;
      letter-spacing: 0;
    }
    .subtitle {
      margin-top: 5px;
      color: var(--muted);
      font-size: 13px;
    }
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: end;
      margin-top: 12px;
      max-width: 100%;
    }
    label {
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
    }
    .control {
      min-width: 0;
    }
    .control-board {
      flex: 1 1 180px;
      max-width: 260px;
    }
    .control-symbol {
      flex: 1 1 260px;
      max-width: 360px;
    }
    .control-search {
      flex: 1 1 150px;
      max-width: 220px;
    }
    .control-frequency {
      flex: 0 1 auto;
      max-width: 100%;
    }
    select, input {
      min-height: 36px;
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      padding: 7px 9px;
      font: inherit;
      font-size: 14px;
    }
    .range {
      display: flex;
      width: max-content;
      max-width: 100%;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      overflow-x: auto;
      background: #fff;
    }
    .range button {
      flex: 0 0 48px;
      border: 0;
      border-right: 1px solid var(--line);
      background: transparent;
      color: var(--muted);
      padding: 0 12px;
      font: inherit;
      font-size: 13px;
      cursor: pointer;
    }
    .range button:last-child { border-right: 0; }
    .range button.active {
      background: #e9f2ff;
      color: var(--blue);
      font-weight: 700;
    }
    .window-position {
      display: grid;
      grid-template-columns: minmax(140px, 1fr) minmax(190px, 260px);
      gap: 8px;
      align-items: center;
      min-width: 0;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      padding: 0 9px;
    }
    .window-position input {
      min-height: auto;
      padding: 0;
      border: 0;
    }
    .window-position span {
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .time-window {
      display: grid;
      grid-template-columns: minmax(120px, 160px) minmax(94px, 116px) auto minmax(170px, 220px) auto minmax(330px, 1fr);
      gap: 10px;
      align-items: end;
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
    }
    .position-meta {
      display: grid;
      gap: 2px;
      min-width: 0;
    }
    .position-meta strong,
    .position-meta span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .position-meta strong {
      font-size: 13px;
      line-height: 1.2;
    }
    .position-meta span {
      color: var(--muted);
      font-size: 12px;
    }
    .window-actions {
      display: flex;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      overflow: hidden;
      background: #fff;
    }
    .window-actions button {
      min-width: 62px;
      border: 0;
      border-right: 1px solid var(--line);
      background: transparent;
      color: var(--text);
      padding: 0 10px;
      font: inherit;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
    }
    .window-actions button:last-child { border-right: 0; }
    .window-actions button:disabled,
    .mini-button:disabled {
      color: #a7b1ba;
      cursor: not-allowed;
      background: #f8fafc;
    }
    .jump-control {
      min-width: 0;
    }
    .overlap-control {
      min-width: 0;
    }
    .position-control {
      min-width: 0;
    }
    .mini-button {
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      padding: 0 12px;
      font: inherit;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }
    .toolbar-button {
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      padding: 0 12px;
      font: inherit;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
      flex: 0 0 auto;
    }
    .toolbar-button:hover {
      border-color: #b8c7d6;
      background: #f8fafc;
    }
    .status-action {
      flex: 0 0 auto;
      display: grid;
      gap: 2px;
      min-width: 158px;
      min-height: 44px;
      border: 1px solid #9dc5ff;
      border-radius: 6px;
      background: #eef6ff;
      color: var(--text);
      padding: 7px 12px;
      font: inherit;
      text-align: left;
      cursor: pointer;
      box-shadow: 0 1px 0 rgba(21, 101, 192, 0.08);
    }
    .status-action:hover {
      border-color: #6fa8ff;
      background: #e4f0ff;
    }
    .status-action span {
      font-size: 13px;
      line-height: 1.2;
      font-weight: 800;
    }
    .status-action small {
      color: var(--blue);
      font-size: 11px;
      line-height: 1.2;
      font-weight: 700;
      white-space: nowrap;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(6, minmax(92px, 1fr));
      gap: 1px;
      border-bottom: 1px solid var(--line);
      background: var(--line);
    }
    .metric {
      min-width: 0;
      background: var(--surface);
      padding: 10px 14px;
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
      font-size: 16px;
      line-height: 1.2;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    main {
      padding: 14px 20px 20px;
    }
    #chart {
      width: 100%;
      height: calc(100vh - 262px);
      min-height: 560px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .empty {
      display: grid;
      place-items: center;
      min-height: 460px;
      color: var(--muted);
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .drawer-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(31, 41, 51, 0.18);
      z-index: 20;
    }
    .drawer-backdrop[hidden] { display: none; }
    .data-drawer {
      position: fixed;
      top: 0;
      right: 0;
      z-index: 30;
      width: min(420px, 100vw);
      height: 100vh;
      background: var(--surface);
      border-left: 1px solid var(--line);
      box-shadow: -16px 0 32px rgba(31, 41, 51, 0.16);
      transform: translateX(100%);
      transition: transform 160ms ease;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .data-drawer.open {
      transform: translateX(0);
    }
    .drawer-header {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
    }
    .drawer-header h2 {
      margin: 0;
      font-size: 16px;
      letter-spacing: 0;
    }
    .drawer-header p {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 12px;
    }
    .source-switcher {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 12px 12px 0;
      background: #fbfcfd;
    }
    .source-switcher button {
      min-height: 32px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--muted);
      padding: 0 10px;
      font: inherit;
      font-size: 12px;
      font-weight: 800;
      cursor: pointer;
    }
    .source-switcher button.active {
      border-color: #9dc5ff;
      background: #eef6ff;
      color: var(--blue);
    }
    .status-list {
      overflow: auto;
      padding: 12px;
      background: #fbfcfd;
    }
    .status-symbol-group {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      margin-bottom: 12px;
      overflow: hidden;
    }
    .status-symbol-header {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: center;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      background: #f8fafc;
    }
    .status-symbol-header strong,
    .status-symbol-header small {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .status-symbol-header small {
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
    }
    .status-row {
      width: 100%;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      text-align: left;
      border: 0;
      border-bottom: 1px solid var(--line);
      border-radius: 0;
      background: #fff;
      color: var(--text);
      padding: 10px;
      font: inherit;
      cursor: pointer;
    }
    .status-row:last-child { border-bottom: 0; }
    .status-row.active {
      border-color: #9dc5ff;
      background: #eef6ff;
    }
    .status-row strong,
    .status-row span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .status-row small {
      display: block;
      margin-top: 4px;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
    }
    .status-pill {
      align-self: start;
      border-radius: 999px;
      background: #edf2f7;
      color: var(--muted);
      padding: 3px 8px;
      font-size: 12px;
      font-weight: 700;
    }
    @media (max-width: 1180px) {
      .time-window {
        grid-template-columns: minmax(120px, 170px) minmax(94px, 116px) auto minmax(170px, 1fr) auto;
      }
      .position-control {
        grid-column: 1 / -1;
      }
      .window-position {
        grid-template-columns: minmax(220px, 1fr) minmax(300px, 360px);
      }
    }
    @media (max-width: 980px) {
      .control-board,
      .control-symbol,
      .control-search,
      .control-frequency {
        max-width: none;
      }
      .time-window {
        grid-template-columns: minmax(120px, 170px) minmax(94px, 116px) minmax(180px, 1fr) auto;
      }
      .window-actions {
        grid-column: 3 / -1;
      }
      .jump-control {
        grid-column: 1 / -2;
      }
      .time-window .mini-button {
        grid-column: -2 / -1;
      }
      .position-control { grid-column: 1 / -1; }
      .summary { grid-template-columns: repeat(3, minmax(90px, 1fr)); }
      #chart { height: 640px; }
    }
    @media (max-width: 620px) {
      .topbar-header {
        display: grid;
      }
      .control,
      .toolbar-button {
        flex-basis: 100%;
        max-width: none;
      }
      .status-action {
        width: 100%;
      }
      .time-window {
        grid-template-columns: 1fr;
      }
      .window-actions,
      .jump-control,
      .time-window .mini-button {
        grid-column: auto;
      }
      .window-actions button {
        flex: 1 1 0;
      }
      .summary { grid-template-columns: repeat(2, minmax(90px, 1fr)); }
      main { padding: 10px; }
      .topbar { padding: 12px; }
      #chart { min-height: 520px; }
    }
  </style>
</head>
<body>
  <script id="kline-payload" type="application/json">__KLINE_PAYLOAD__</script>
  <header class="topbar">
    <div class="topbar-header">
      <div class="title-block">
        <h1>K-line Cache Viewer</h1>
        <div class="subtitle" id="datasetMeta"></div>
      </div>
      <button type="button" class="status-action" id="dataStatusButton" aria-expanded="false">
        <span>Data Status</span>
        <small id="dataStatusButtonMeta">Cached series</small>
      </button>
    </div>
    <div class="controls">
      <label class="control control-board">Market / Board
        <select id="boardSelect"></select>
      </label>
      <label class="control control-symbol">Symbol
        <select id="symbolSelect"></select>
      </label>
      <label class="control control-search">Search
        <input id="searchInput" type="search" autocomplete="off" placeholder="Code or name">
      </label>
      <label class="control control-frequency">Frequency
        <div class="range" id="frequencyButtons" aria-label="Frequency"></div>
      </label>
    </div>
    <div class="time-window" id="timeWindowBar">
      <label>Window
        <select id="windowSizeSelect">
          <option value="100">100 bars</option>
          <option value="300">300 bars</option>
          <option value="1000">1000 bars</option>
          <option value="5000">5000 bars</option>
          <option value="all">All available</option>
        </select>
      </label>
      <label class="overlap-control">Overlap
        <select id="windowOverlapSelect">
          <option value="0">0%</option>
          <option value="0.1">10%</option>
          <option value="0.2">20%</option>
          <option value="0.5">50%</option>
          <option value="0.8" selected>80%</option>
        </select>
      </label>
      <div class="window-actions" aria-label="Window navigation">
        <button type="button" id="olderPageButton">Older</button>
        <button type="button" id="newerPageButton">Newer</button>
        <button type="button" id="latestPageButton">Latest</button>
      </div>
      <label class="jump-control">Jump to
        <input id="jumpTimeInput" type="datetime-local" autocomplete="off">
      </label>
      <button type="button" class="mini-button" id="jumpTimeButton">Go</button>
      <label class="position-control">Position
        <div class="window-position">
          <input id="windowSlider" type="range" min="0" max="0" value="0">
          <div class="position-meta" id="windowMeta">
            <strong id="windowRowsMeta">Rows</strong>
            <span id="windowTimeMeta">Latest window</span>
          </div>
        </div>
      </label>
    </div>
  </header>
  <section class="summary" id="summary"></section>
  <main>
    <div id="chart"></div>
  </main>
  <div class="drawer-backdrop" id="drawerBackdrop" hidden></div>
  <aside class="data-drawer" id="dataStatusDrawer" aria-label="Data status">
    <div class="drawer-header">
      <div>
        <h2>Data Status</h2>
        <p id="dataStatusMeta"></p>
      </div>
      <button type="button" class="toolbar-button" id="closeDrawerButton">Close</button>
    </div>
    <div class="source-switcher" id="sourceButtons" aria-label="Data source"></div>
    <div class="status-list" id="dataStatusList"></div>
  </aside>
  <script>
    const payload = JSON.parse(document.getElementById("kline-payload").textContent);
    const dynamicMode = payload.mode === "dynamic";
    const DYNAMIC_BUFFER_MULTIPLIER = 3;
    const KLINE_DISPLAY_TIME_ZONE = "Asia/Shanghai";
    const KLINE_DISPLAY_TIME_ZONE_OFFSET = "+08:00";
    let sources = normalizeSources(payload);
    const state = {
      sourceId: sources[0]?.source_id || "default",
      symbol: sources[0]?.symbols?.[0]?.symbol || "",
      frequency: sources[0]?.symbols?.[0]?.series?.[0]?.frequency || payload.frequency || "1d",
      board: "all",
      search: "",
      windowSize: String(payload.default_window_size || payload.limit || 300),
      windowOverlap: String(payload.default_window_overlap ?? 0.8),
      windowStart: 0,
      drawerOpen: false,
      loading: false,
      error: "",
      seriesData: null,
    };

    const boardSelect = document.getElementById("boardSelect");
    const symbolSelect = document.getElementById("symbolSelect");
    const searchInput = document.getElementById("searchInput");
    const frequencyButtons = document.getElementById("frequencyButtons");
    const windowSizeSelect = document.getElementById("windowSizeSelect");
    const windowOverlapSelect = document.getElementById("windowOverlapSelect");
    const windowSlider = document.getElementById("windowSlider");
    const windowMeta = document.getElementById("windowMeta");
    const windowRowsMeta = document.getElementById("windowRowsMeta");
    const windowTimeMeta = document.getElementById("windowTimeMeta");
    const olderPageButton = document.getElementById("olderPageButton");
    const newerPageButton = document.getElementById("newerPageButton");
    const latestPageButton = document.getElementById("latestPageButton");
    const jumpTimeInput = document.getElementById("jumpTimeInput");
    const jumpTimeButton = document.getElementById("jumpTimeButton");
    const dataStatusButton = document.getElementById("dataStatusButton");
    const dataStatusButtonMeta = document.getElementById("dataStatusButtonMeta");
    const closeDrawerButton = document.getElementById("closeDrawerButton");
    const drawerBackdrop = document.getElementById("drawerBackdrop");
    const dataStatusDrawer = document.getElementById("dataStatusDrawer");
    const sourceButtons = document.getElementById("sourceButtons");
    const dataStatusList = document.getElementById("dataStatusList");
    const dataStatusMeta = document.getElementById("dataStatusMeta");
    const summary = document.getElementById("summary");
    const datasetMeta = document.getElementById("datasetMeta");
    const chart = document.getElementById("chart");

    function apiUrl(path) {
      const baseUrl = String(payload.data_api_base_url || "").replace(/\\/+$/, "");
      return baseUrl ? `${baseUrl}${path}` : path;
    }

    function normalizeSources(payload) {
      if (Array.isArray(payload.sources) && payload.sources.length) {
        return payload.sources;
      }
      return [{
        source_id: payload.source_id || "default",
        source_label: payload.source_label || "Cache",
        frequency: payload.frequency || "1d",
        frequencies: payload.frequencies || [payload.frequency || "1d"],
        symbols: payload.symbols || [],
      }];
    }

    function currentSource() {
      return sources.find((source) => source.source_id === state.sourceId) || sources[0] || { symbols: [] };
    }

    function currentSymbols() {
      return currentSource().symbols || [];
    }

    function currentBySymbol() {
      return new Map(currentSymbols().map((item) => [item.symbol, item]));
    }

    function selectedItem() {
      return currentBySymbol().get(state.symbol) || null;
    }

    function boardKey(item) {
      return [item.exchange || "", item.board || ""].filter(Boolean).join(" / ") || "Unclassified";
    }

    function optionLabel(item) {
      const board = boardKey(item);
      return [item.symbol, item.name, board].filter(Boolean).join("  ");
    }

    function seriesList(item) {
      if (!item) {
        return [];
      }
      if (Array.isArray(item.series) && item.series.length) {
        return item.series;
      }
      return [{ frequency: payload.frequency || "1d", adjust: payload.adjust || "", rows: (item.bars || []).length, bars: item.bars || [] }];
    }

    function seriesByFrequency(item) {
      return new Map(seriesList(item).map((series) => [series.frequency, series]));
    }

    function currentSeries(item) {
      if (!item) {
        return null;
      }
      const byFrequency = seriesByFrequency(item);
      if (!byFrequency.has(state.frequency)) {
        state.frequency = seriesList(item)[0]?.frequency || "";
      }
      return byFrequency.get(state.frequency) || seriesList(item)[0] || null;
    }

    function isSeriesDataCurrent() {
      return Boolean(
        state.seriesData
        && state.seriesData.source_id === state.sourceId
        && state.seriesData.symbol === state.symbol
        && state.seriesData.frequency === state.frequency
      );
    }

    function activeSeries(item) {
      if (dynamicMode && isSeriesDataCurrent()) {
        return state.seriesData;
      }
      return currentSeries(item);
    }

    function hasExplicitTimeZone(value) {
      return /(?:Z|[+-]\\d{2}:?\\d{2})$/i.test(String(value || "").trim());
    }

    function parseBarDateTime(value, frequency) {
      if (!value) return null;
      if (value instanceof Date) {
        return Number.isNaN(value.getTime()) ? null : value;
      }
      const text = String(value).trim();
      const dateOnly = text.match(/^(\\d{4}-\\d{2}-\\d{2})$/);
      if (dateOnly) {
        return new Date(`${dateOnly[1]}T00:00:00Z`);
      }
      const dateTime = text.match(/^(\\d{4}-\\d{2}-\\d{2})[T ](\\d{2}:\\d{2}(?::\\d{2}(?:\\.\\d+)?)?)(.*)$/);
      if (dateTime && !hasExplicitTimeZone(text)) {
        return new Date(`${dateTime[1]}T${dateTime[2]}Z`);
      }
      const parsed = new Date(text);
      return Number.isNaN(parsed.getTime()) ? null : parsed;
    }

    function displayDateTimeParts(value, frequency) {
      const date = parseBarDateTime(value, frequency);
      if (!date) return null;
      const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: KLINE_DISPLAY_TIME_ZONE,
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hourCycle: "h23",
      }).formatToParts(date);
      return Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
    }

    function formatBarDateTime(value, frequency) {
      if (!value) return "";
      if ((frequency || state.frequency) === "1d") {
        return String(value).slice(0, 10);
      }
      const parts = displayDateTimeParts(value, frequency);
      if (!parts) return String(value);
      return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
    }

    function formatBarRange(startValue, endValue, frequency) {
      return [formatBarDateTime(startValue, frequency), formatBarDateTime(endValue, frequency)]
        .filter(Boolean)
        .join(" to ");
    }

    function utcDateTimeString(date) {
      return [
        date.getUTCFullYear(),
        String(date.getUTCMonth() + 1).padStart(2, "0"),
        String(date.getUTCDate()).padStart(2, "0"),
      ].join("-") + "T" + [
        String(date.getUTCHours()).padStart(2, "0"),
        String(date.getUTCMinutes()).padStart(2, "0"),
        String(date.getUTCSeconds()).padStart(2, "0"),
      ].join(":");
    }

    function jumpInputToApiValue(value, daily) {
      if (!value) return "";
      const text = String(value).trim();
      if (daily) {
        return text.slice(0, 10);
      }
      const normalized = text.includes("T") ? text : text.replace(" ", "T");
      const withSeconds = normalized.length === 16 ? `${normalized}:00` : normalized;
      const date = new Date(`${withSeconds}${KLINE_DISPLAY_TIME_ZONE_OFFSET}`);
      return Number.isNaN(date.getTime()) ? text : utcDateTimeString(date);
    }

    function populateBoards() {
      const symbols = currentSymbols();
      const boards = Array.from(new Set(symbols.map(boardKey).filter(Boolean))).sort();
      boardSelect.innerHTML = [
        `<option value="all">All symbols (${symbols.length})</option>`,
        ...boards.map((board) => {
          const count = symbols.filter((item) => boardKey(item) === board).length;
          return `<option value="${escapeHtml(board)}">${escapeHtml(board)} (${count})</option>`;
        }),
      ].join("");
      if (state.board !== "all" && !boards.includes(state.board)) {
        state.board = "all";
      }
      boardSelect.value = state.board;
    }

    function filteredSymbols() {
      const query = state.search.trim().toLowerCase();
      return currentSymbols().filter((item) => {
        const matchesBoard = state.board === "all" || boardKey(item) === state.board;
        const target = `${item.symbol} ${item.name || ""} ${item.exchange || ""} ${item.board || ""}`.toLowerCase();
        return matchesBoard && (!query || target.includes(query));
      });
    }

    function populateSymbols() {
      const visible = filteredSymbols();
      const previousSymbol = state.symbol;
      if (!visible.some((item) => item.symbol === state.symbol)) {
        state.symbol = visible[0]?.symbol || "";
      }
      symbolSelect.innerHTML = visible.map((item) => {
        const selected = item.symbol === state.symbol ? " selected" : "";
        return `<option value="${escapeHtml(item.symbol)}"${selected}>${escapeHtml(optionLabel(item))}</option>`;
      }).join("");
      populateFrequencies();
      if (previousSymbol !== state.symbol || dynamicMode) {
        state.seriesData = null;
      }
      if (!dynamicMode && previousSymbol !== state.symbol) {
        setWindowToLatest(currentSeries(selectedItem()));
      }
    }

    function populateFrequencies() {
      const item = selectedItem();
      const series = seriesList(item);
      if (!series.some((entry) => entry.frequency === state.frequency)) {
        state.frequency = series[0]?.frequency || "";
      }
      frequencyButtons.innerHTML = series.map((entry) => {
        const active = entry.frequency === state.frequency ? " active" : "";
        return `<button type="button" data-frequency="${escapeHtml(entry.frequency)}" class="${active.trim()}">${escapeHtml(entry.frequency)}</button>`;
      }).join("");
    }

    function windowSizeValue(series) {
      const loaded = (series?.bars || []).length;
      if (state.windowSize === "all") {
        return loaded;
      }
      return Math.min(Number(state.windowSize), loaded);
    }

    function availableWindowRows(series) {
      const embedded = (series?.bars || []).length;
      return dynamicMode ? Number(series?.rows || embedded || 0) : embedded;
    }

    function requestedWindowSize(series) {
      const total = availableWindowRows(series);
      if (state.windowSize === "all") {
        return Math.max(1, total);
      }
      return Math.max(1, Number(state.windowSize) || 300);
    }

    function bufferedWindowSize(series) {
      const total = availableWindowRows(series);
      const visibleSize = requestedWindowSize(series);
      if (state.windowSize === "all") {
        return Math.max(1, total);
      }
      return Math.max(1, Math.min(total || visibleSize, visibleSize * DYNAMIC_BUFFER_MULTIPLIER));
    }

    function loadLimit(series) {
      return state.windowSize === "all" ? 0 : bufferedWindowSize(series);
    }

    function clamp(value, min, max) {
      return Math.min(Math.max(value, min), max);
    }

    function windowOverlapRatio() {
      const value = Number(state.windowOverlap);
      return Number.isFinite(value) ? clamp(value, 0, 0.9) : 0.8;
    }

    function pageStepSize(series) {
      const size = requestedWindowSize(series);
      if (state.windowSize === "all") {
        return size;
      }
      return Math.max(1, Math.round(size * (1 - windowOverlapRatio())));
    }

    function globalWindowOffset(series) {
      if (!dynamicMode) {
        return state.windowStart;
      }
      return Number(series?.offset || 0) + state.windowStart;
    }

    function globalMaxWindowOffset(series) {
      const total = availableWindowRows(series);
      const visibleSize = requestedWindowSize(series);
      return Math.max(0, total - visibleSize);
    }

    function targetBufferOffset(targetWindowOffset, series) {
      const visibleSize = requestedWindowSize(series);
      const bufferSize = bufferedWindowSize(series);
      const total = availableWindowRows(series);
      const maxBufferOffset = Math.max(0, total - bufferSize);
      const centeredOffset = targetWindowOffset - Math.floor((bufferSize - visibleSize) / 2);
      return clamp(centeredOffset, 0, maxBufferOffset);
    }

    function canRenderGlobalOffset(targetWindowOffset, series) {
      if (!dynamicMode || !series) {
        return false;
      }
      const visibleSize = Math.min(requestedWindowSize(series), (series.bars || []).length);
      const bufferOffset = Number(series.offset || 0);
      const maxLocalStart = Math.max(0, (series.bars || []).length - visibleSize);
      return targetWindowOffset >= bufferOffset && targetWindowOffset <= bufferOffset + maxLocalStart;
    }

    function renderGlobalOffset(targetWindowOffset, series) {
      const visibleSize = Math.min(requestedWindowSize(series), (series?.bars || []).length);
      const maxLocalStart = Math.max(0, (series?.bars || []).length - visibleSize);
      state.windowStart = clamp(targetWindowOffset - Number(series?.offset || 0), 0, maxLocalStart);
      render();
    }

    function sortableTimeValue(value) {
      const text = String(value || "").trim().replace(" ", "T");
      if (!text) {
        return "";
      }
      if (text.length === 10) {
        return `${text}T00:00:00`;
      }
      if (text.includes("T") && text.length === 16) {
        return `${text}:00`;
      }
      return text;
    }

    function localWindowStartForTime(series, start) {
      const bars = series?.bars || [];
      const visibleSize = Math.min(requestedWindowSize(series), bars.length);
      const maxLocalStart = Math.max(0, bars.length - visibleSize);
      const target = sortableTimeValue(start);
      let index = 0;
      for (let cursor = 0; cursor < bars.length; cursor += 1) {
        if (sortableTimeValue(bars[cursor].date) > target) {
          break;
        }
        index = cursor;
      }
      return clamp(index, 0, maxLocalStart);
    }

    function firstVisibleBarDate(series) {
      const bars = series?.bars || [];
      if (!bars.length) {
        return "";
      }
      const size = dynamicMode
        ? Math.min(requestedWindowSize(series), bars.length)
        : windowSizeValue(series);
      const maxStart = Math.max(0, bars.length - size);
      return bars[clamp(state.windowStart, 0, maxStart)]?.date || "";
    }

    function currentJumpStart() {
      const series = activeSeries(selectedItem());
      const daily = (series?.frequency || state.frequency) === "1d";
      const raw = jumpTimeInput.value.trim();
      return raw ? jumpInputToApiValue(raw, daily) : firstVisibleBarDate(series);
    }

    function syncJumpInputToWindow(series, bars) {
      configureJumpControl(series);
      if (bars.length) {
        const daily = (series?.frequency || state.frequency) === "1d";
        jumpTimeInput.value = toJumpInputValue(bars[0].date, daily);
      } else if (!state.loading) {
        jumpTimeInput.value = "";
      }
    }

    function setWindowToLatest(series) {
      const loaded = (series?.bars || []).length;
      const size = windowSizeValue(series);
      state.windowStart = Math.max(0, loaded - size);
    }

    function visibleBars(series) {
      const bars = series?.bars || [];
      if (dynamicMode) {
        const size = Math.min(requestedWindowSize(series), bars.length);
        const maxStart = Math.max(0, bars.length - size);
        state.windowStart = clamp(state.windowStart, 0, maxStart);
        if (size >= bars.length) {
          return bars;
        }
        return bars.slice(state.windowStart, state.windowStart + size);
      }
      const size = windowSizeValue(series);
      const maxStart = Math.max(0, bars.length - size);
      state.windowStart = Math.min(Math.max(0, state.windowStart), maxStart);
      if (size >= bars.length) {
        return bars;
      }
      return bars.slice(state.windowStart, state.windowStart + size);
    }

    function updateWindowControls(series, bars) {
      const loaded = bars.length;
      const bufferCount = (series?.bars || []).length;
      const total = availableWindowRows(series) || bufferCount || loaded || 0;
      const size = dynamicMode
        ? Math.min(requestedWindowSize(series), Math.max(1, bufferCount || total))
        : windowSizeValue(series);
      const offset = globalWindowOffset(series);
      const globalMaxStart = dynamicMode ? globalMaxWindowOffset(series) : Math.max(0, total - size);
      windowSizeSelect.value = state.windowSize;
      windowOverlapSelect.value = state.windowOverlap;
      windowOverlapSelect.disabled = state.loading || globalMaxStart === 0;
      windowSlider.max = String(globalMaxStart);
      windowSlider.value = String(Math.min(offset, globalMaxStart));
      windowSlider.disabled = state.loading || globalMaxStart === 0;
      const startRow = dynamicMode
        ? (loaded ? offset + 1 : 0)
        : (loaded ? state.windowStart + 1 : 0);
      const endRow = dynamicMode
        ? (loaded ? offset + loaded : 0)
        : (loaded ? Math.min(bufferCount, state.windowStart + bars.length) : 0);
      const totalLabel = compact(total);
      windowRowsMeta.textContent = loaded ? `Rows ${startRow}-${endRow} / ${totalLabel}` : (total ? `Rows 0 / ${compact(total)}` : "No bars");
      windowTimeMeta.textContent = loaded
        ? formatBarRange(bars[0].date, bars[bars.length - 1].date, series?.frequency || state.frequency)
        : formatBarRange(series?.first_bar, series?.last_bar, series?.frequency || state.frequency) || "No window selected";
      windowMeta.title = [windowRowsMeta.textContent, windowTimeMeta.textContent].filter(Boolean).join(" | ");
      syncJumpInputToWindow(series, bars);
      olderPageButton.disabled = state.loading || !loaded || offset <= 0;
      newerPageButton.disabled = state.loading || !loaded || offset >= globalMaxStart;
      latestPageButton.disabled = state.loading || !loaded || offset >= globalMaxStart;
      jumpTimeButton.disabled = state.loading || !total;
    }

    function configureJumpControl(series) {
      const frequency = series?.frequency || state.frequency;
      const daily = frequency === "1d";
      jumpTimeInput.type = daily ? "date" : "datetime-local";
      jumpTimeInput.step = String(frequencyStepSeconds(frequency));
      jumpTimeInput.min = toJumpInputValue(series?.first_bar || "", daily);
      jumpTimeInput.max = toJumpInputValue(series?.last_bar || "", daily);
      jumpTimeInput.title = formatBarRange(series?.first_bar, series?.last_bar, frequency);
    }

    function frequencyStepSeconds(frequency) {
      const steps = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "60m": 3600,
        "4h": 14400,
        "1d": 86400,
      };
      return steps[frequency] || 60;
    }

    function toJumpInputValue(value, daily) {
      if (!value) {
        return "";
      }
      if (daily) {
        return String(value).slice(0, 10);
      }
      const parts = displayDateTimeParts(value, state.frequency);
      if (!parts) return "";
      return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
    }

    function movingAverage(bars, days) {
      return bars.map((_, index) => {
        if (index + 1 < days) {
          return null;
        }
        const window = bars.slice(index + 1 - days, index + 1);
        return window.reduce((sum, bar) => sum + Number(bar.close), 0) / days;
      });
    }

    function renderSummary(item, series, bars) {
      if (!item || !bars.length) {
        summary.innerHTML = `<div class="metric"><span>Status</span><strong>No data</strong></div>`;
        return;
      }
      const last = bars[bars.length - 1];
      const first = bars[0];
      const change = last.close - first.close;
      const changePct = first.close ? (change / first.close) * 100 : 0;
      summary.innerHTML = [
        metric("Source", currentSource().source_label || currentSource().source_id || "Cache"),
        metric("Symbol", `${item.symbol} ${item.name || ""}`),
        metric("Frequency", series?.frequency || state.frequency),
        metric("Time Span", formatBarRange(first.date, last.date, series?.frequency || state.frequency)),
        metric("Close", fixed(last.close)),
        metric("Change", `${fixed(change)} (${fixed(changePct)}%)`),
      ].join("");
    }

    function metric(label, value) {
      return `<div class="metric"><span>${escapeHtml(label)}</span><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`;
    }

    function render() {
      updateDatasetMeta();
      const item = selectedItem();
      if (!item) {
        chart.className = "empty";
        chart.textContent = "No matching symbol";
        renderSummary(null, null, []);
        return;
      }
      const series = activeSeries(item);
      if (!series) {
        chart.className = "empty";
        chart.textContent = "No data for selected frequency";
        renderSummary(item, null, []);
        return;
      }
      if (dynamicMode && !isSeriesDataCurrent()) {
        const bars = [];
        chart.className = "empty";
        chart.textContent = state.error || (state.loading ? "Loading data..." : "No window loaded");
        updateWindowControls(series, bars);
        renderSummary(item, series, bars);
        return;
      }
      chart.className = "";
      chart.textContent = "";
      if (!window.Plotly) {
        chart.className = "empty";
        chart.textContent = "Chart library failed to load";
        return;
      }
      const bars = visibleBars(series);
      updateWindowControls(series, bars);
      renderSummary(item, series, bars);
      const x = bars.map((bar) => formatBarDateTime(bar.date, series?.frequency || state.frequency));
      const upColor = "#d32f2f";
      const downColor = "#00897b";
      const volumeColors = bars.map((bar) => Number(bar.close) >= Number(bar.open) ? upColor : downColor);
      const traces = [
        {
          type: "candlestick",
          x,
          open: bars.map((bar) => bar.open),
          high: bars.map((bar) => bar.high),
          low: bars.map((bar) => bar.low),
          close: bars.map((bar) => bar.close),
          name: "K",
          increasing: { line: { color: upColor }, fillcolor: upColor },
          decreasing: { line: { color: downColor }, fillcolor: downColor },
          yaxis: "y",
        },
        {
          type: "scatter",
          mode: "lines",
          x,
          y: movingAverage(bars, 5),
          name: "MA5",
          line: { color: "#f9a825", width: 1.4 },
          yaxis: "y",
        },
        {
          type: "scatter",
          mode: "lines",
          x,
          y: movingAverage(bars, 20),
          name: "MA20",
          line: { color: "#1565c0", width: 1.4 },
          yaxis: "y",
        },
        {
          type: "bar",
          x,
          y: bars.map((bar) => bar.volume),
          name: "Volume",
          marker: { color: volumeColors, opacity: 0.55 },
          yaxis: "y2",
        },
      ];
      const layout = {
        margin: { l: 64, r: 24, t: 44, b: 38 },
        showlegend: true,
        legend: {
          orientation: "h",
          x: 0,
          y: 1.12,
          xanchor: "left",
          yanchor: "bottom",
        },
        hovermode: "x unified",
        plot_bgcolor: "#ffffff",
        paper_bgcolor: "#ffffff",
        xaxis: {
          rangeslider: { visible: false },
          showgrid: true,
          gridcolor: "#edf1f5",
          type: "category",
          nticks: 9,
        },
        yaxis: {
          domain: [0.28, 1],
          title: "Price",
          showgrid: true,
          gridcolor: "#edf1f5",
          tickformat: ".2f",
          fixedrange: false,
        },
        yaxis2: {
          domain: [0, 0.2],
          title: "Volume",
          showgrid: true,
          gridcolor: "#edf1f5",
          fixedrange: false,
        },
        bargap: 0,
      };
      Plotly.newPlot(chart, traces, layout, { responsive: true, displaylogo: false });
    }

    function renderSourceButtons() {
      sourceButtons.innerHTML = sources.map((source) => {
        const active = source.source_id === state.sourceId ? " active" : "";
        const count = (source.symbols || []).length;
        const label = `${source.source_label || source.source_id} (${count})`;
        return `<button type="button" class="${active.trim()}" data-source="${escapeHtml(source.source_id)}">${escapeHtml(label)}</button>`;
      }).join("");
    }

    function renderDataStatus() {
      const source = currentSource();
      const symbols = currentSymbols();
      const totalSeries = symbols.reduce((count, item) => count + seriesList(item).length, 0);
      renderSourceButtons();
      dataStatusMeta.textContent = `${source.source_label || source.source_id} | ${symbols.length} symbols | ${totalSeries} cached series`;
      dataStatusButtonMeta.textContent = `${source.source_label || source.source_id} | ${totalSeries} series`;
      if (!totalSeries) {
        dataStatusList.innerHTML = `<div class="empty">No cached data</div>`;
        return;
      }
      dataStatusList.innerHTML = symbols.map((item) => {
        const series = seriesList(item);
        const rows = series.map((entry) => {
          const active = item.symbol === state.symbol && entry.frequency === state.frequency ? " active" : "";
          const years = Array.isArray(entry.years) ? entry.years.join(", ") : "";
          const range = formatBarRange(entry.first_bar, entry.last_bar, entry.frequency);
          const details = [
            range,
            `${compact(entry.rows || (entry.bars || []).length)} rows`,
            years ? `years ${years}` : "",
            entry.adjust ? `adjust ${entry.adjust}` : "",
          ].filter(Boolean).join(" | ");
          return `
            <button type="button" class="status-row${active}" data-source="${escapeHtml(source.source_id)}" data-symbol="${escapeHtml(item.symbol)}" data-frequency="${escapeHtml(entry.frequency)}">
              <span>
                <strong>${escapeHtml(entry.frequency)}</strong>
                <small>${escapeHtml(details)}</small>
              </span>
              <span class="status-pill">${escapeHtml(entry.frequency)}</span>
            </button>
          `;
        }).join("");
        return `
          <section class="status-symbol-group">
            <div class="status-symbol-header">
              <strong>${escapeHtml(item.symbol)} ${escapeHtml(item.name || "")}</strong>
              <small>${series.length} frequencies</small>
            </div>
            ${rows}
          </section>
        `;
      }).join("");
    }

    function switchSource(sourceId) {
      if (state.sourceId === sourceId) {
        return;
      }
      state.sourceId = sourceId;
      state.board = "all";
      state.search = "";
      state.seriesData = null;
      searchInput.value = "";
      populateBoards();
      populateSymbols();
      loadLatestOrRender();
    }

    function toggleDataStatus(open = !state.drawerOpen) {
      state.drawerOpen = open;
      dataStatusDrawer.classList.toggle("open", state.drawerOpen);
      drawerBackdrop.hidden = !state.drawerOpen;
      dataStatusButton.setAttribute("aria-expanded", String(state.drawerOpen));
      if (state.drawerOpen) {
        renderDataStatus();
      }
    }

    function fixed(value) {
      return Number(value).toFixed(2);
    }

    function compact(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) {
        return "0";
      }
      if (number >= 100000000) {
        return `${fixed(number / 100000000)}B`;
      }
      if (number >= 10000) {
        return `${fixed(number / 10000)}W`;
      }
      return `${Math.round(number)}`;
    }

    function escapeHtml(value) {
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
    }

    function ensureWindowOption() {
      if (!Array.from(windowSizeSelect.options).some((option) => option.value === state.windowSize)) {
        windowSizeSelect.insertAdjacentHTML(
          "beforeend",
          `<option value="${escapeHtml(state.windowSize)}">${escapeHtml(state.windowSize)} bars</option>`
        );
      }
      windowSizeSelect.value = state.windowSize;
    }

    function ensureWindowOverlapOption() {
      state.windowOverlap = String(windowOverlapRatio());
      if (!Array.from(windowOverlapSelect.options).some((option) => option.value === state.windowOverlap)) {
        windowOverlapSelect.insertAdjacentHTML(
          "beforeend",
          `<option value="${escapeHtml(state.windowOverlap)}">${escapeHtml(formatPercent(windowOverlapRatio()))}</option>`
        );
      }
      windowOverlapSelect.value = state.windowOverlap;
    }

    function formatPercent(value) {
      return `${Math.round(Number(value) * 100)}%`;
    }

    async function loadManifest() {
      state.loading = true;
      state.error = "";
      chart.className = "empty";
      chart.textContent = "Loading local data index...";
      try {
        const response = await fetch(apiUrl("/api/kline/manifest"), { cache: "no-store" });
        const manifest = await response.json();
        if (!response.ok || manifest.error) {
          throw new Error(manifest.error || `Manifest request failed: ${response.status}`);
        }
        sources = normalizeSources(manifest);
        if (!sources.some((source) => source.source_id === state.sourceId)) {
          state.sourceId = sources[0]?.source_id || "default";
        }
        state.board = "all";
        state.search = "";
        searchInput.value = "";
        state.symbol = currentSymbols()[0]?.symbol || "";
        state.frequency = seriesList(selectedItem())[0]?.frequency || manifest.frequency || "1d";
        state.seriesData = null;
        populateBoards();
        populateSymbols();
        renderDataStatus();
        await loadCurrentBars({ anchor: "latest" });
      } catch (error) {
        state.error = error instanceof Error ? error.message : String(error);
        state.loading = false;
        render();
      }
    }

    async function loadCurrentBars({ offset = null, start = "", anchor = "latest" } = {}) {
      if (!dynamicMode) {
        render();
        return;
      }
      const item = selectedItem();
      const metadata = currentSeries(item);
      if (!item || !metadata) {
        state.seriesData = null;
        state.loading = false;
        render();
        return;
      }
      state.loading = true;
      state.error = "";
      render();
      const params = new URLSearchParams({
        source_id: state.sourceId,
        symbol: item.symbol,
        frequency: metadata.frequency,
        limit: String(loadLimit(metadata)),
      });
      if (metadata.adjust || payload.adjust) {
        params.set("adjust", metadata.adjust || payload.adjust);
      }
      if (start) {
        params.set("start", start);
      } else if (offset !== null && offset !== undefined) {
        params.set("offset", String(targetBufferOffset(Number(offset), metadata)));
      } else {
        params.set("anchor", anchor);
      }
      try {
        const response = await fetch(apiUrl(`/api/kline/bars?${params.toString()}`), { cache: "no-store" });
        const result = await response.json();
        if (!response.ok || result.error) {
          throw new Error(result.error || `Bars request failed: ${response.status}`);
        }
        state.seriesData = result;
        const visibleSize = Math.min(requestedWindowSize(result), (result.bars || []).length);
        const maxLocalStart = Math.max(0, (result.bars || []).length - visibleSize);
        if (start) {
          state.windowStart = localWindowStartForTime(result, start);
        } else if (offset !== null && offset !== undefined) {
          state.windowStart = clamp(Number(offset) - Number(result.offset || 0), 0, maxLocalStart);
        } else {
          state.windowStart = maxLocalStart;
        }
        state.loading = false;
        renderDataStatus();
        render();
      } catch (error) {
        state.error = error instanceof Error ? error.message : String(error);
        state.seriesData = null;
        state.loading = false;
        render();
      }
    }

    function loadLatestOrRender() {
      renderDataStatus();
      if (dynamicMode) {
        loadCurrentBars({ anchor: "latest" });
      } else {
        setWindowToLatest(currentSeries(selectedItem()));
        render();
      }
    }

    function navigateToGlobalOffset(targetWindowOffset) {
      if (!dynamicMode) {
        state.windowStart = targetWindowOffset;
        render();
        return;
      }
      const series = activeSeries(selectedItem());
      if (canRenderGlobalOffset(targetWindowOffset, series)) {
        renderGlobalOffset(targetWindowOffset, series);
      } else {
        loadCurrentBars({ offset: targetWindowOffset });
      }
    }

    function loadWindowForStart(start) {
      if (!start) {
        loadLatestOrRender();
        return;
      }
      if (dynamicMode) {
        loadCurrentBars({ start });
        return;
      }
      const series = currentSeries(selectedItem());
      state.windowStart = localWindowStartForTime(series, start);
      render();
    }

    function loadWindowForCurrentStart() {
      loadWindowForStart(currentJumpStart());
    }

    function pageOffset(direction) {
      const series = activeSeries(selectedItem());
      const total = availableWindowRows(series);
      const size = requestedWindowSize(series);
      const step = pageStepSize(series);
      const maxStart = Math.max(0, total - size);
      const current = dynamicMode ? globalWindowOffset(series) : state.windowStart;
      return direction === "older"
        ? Math.max(0, current - step)
        : Math.min(maxStart, current + step);
    }

    function jumpToTime() {
      const raw = jumpTimeInput.value.trim();
      if (!raw) {
        return;
      }
      loadWindowForStart(raw);
    }

    boardSelect.addEventListener("change", () => {
      state.board = boardSelect.value;
      populateSymbols();
      loadLatestOrRender();
    });
    symbolSelect.addEventListener("change", () => {
      state.symbol = symbolSelect.value;
      state.seriesData = null;
      populateFrequencies();
      loadLatestOrRender();
    });
    searchInput.addEventListener("input", () => {
      state.search = searchInput.value;
      populateSymbols();
      loadLatestOrRender();
    });
    frequencyButtons.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-frequency]");
      if (!button) {
        return;
      }
      const start = currentJumpStart();
      state.frequency = button.dataset.frequency;
      state.seriesData = null;
      populateFrequencies();
      loadWindowForStart(start);
    });
    windowSizeSelect.addEventListener("change", () => {
      state.windowSize = windowSizeSelect.value;
      loadWindowForCurrentStart();
    });
    windowOverlapSelect.addEventListener("change", () => {
      state.windowOverlap = windowOverlapSelect.value;
      render();
    });
    windowSlider.addEventListener("input", () => {
      const targetWindowOffset = Number(windowSlider.value);
      if (dynamicMode) {
        const series = activeSeries(selectedItem());
        if (canRenderGlobalOffset(targetWindowOffset, series)) {
          renderGlobalOffset(targetWindowOffset, series);
        } else {
          const size = requestedWindowSize(series);
          const total = Number(series?.rows || 0);
          windowRowsMeta.textContent = total
            ? `Rows ${targetWindowOffset + 1}-${Math.min(total, targetWindowOffset + size)} / ${compact(total)}`
            : `Offset ${targetWindowOffset}`;
          windowTimeMeta.textContent = "Release to load window";
        }
        return;
      }
      navigateToGlobalOffset(targetWindowOffset);
    });
    windowSlider.addEventListener("change", () => {
      if (dynamicMode) {
        const targetWindowOffset = Number(windowSlider.value);
        const series = activeSeries(selectedItem());
        if (!canRenderGlobalOffset(targetWindowOffset, series)) {
          loadCurrentBars({ offset: targetWindowOffset });
        }
      }
    });
    olderPageButton.addEventListener("click", () => {
      navigateToGlobalOffset(pageOffset("older"));
    });
    newerPageButton.addEventListener("click", () => {
      navigateToGlobalOffset(pageOffset("newer"));
    });
    latestPageButton.addEventListener("click", () => loadLatestOrRender());
    jumpTimeButton.addEventListener("click", jumpToTime);
    jumpTimeInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        jumpToTime();
      }
    });
    dataStatusButton.addEventListener("click", () => toggleDataStatus());
    closeDrawerButton.addEventListener("click", () => toggleDataStatus(false));
    drawerBackdrop.addEventListener("click", () => toggleDataStatus(false));
    sourceButtons.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-source]");
      if (!button) {
        return;
      }
      switchSource(button.dataset.source);
    });
    dataStatusList.addEventListener("click", (event) => {
      const row = event.target.closest("button[data-source][data-symbol][data-frequency]");
      if (!row) {
        return;
      }
      state.sourceId = row.dataset.source;
      state.symbol = row.dataset.symbol;
      state.frequency = row.dataset.frequency;
      state.board = "all";
      state.search = "";
      state.seriesData = null;
      searchInput.value = "";
      populateBoards();
      populateSymbols();
      populateFrequencies();
      toggleDataStatus(false);
      loadLatestOrRender();
    });
    window.addEventListener("resize", () => {
      if (chart.data) {
        Plotly.Plots.resize(chart);
      }
    });

    function updateDatasetMeta() {
      const source = currentSource();
      const symbols = currentSymbols();
      const frequencies = source.frequencies || payload.frequencies || [payload.frequency];
      const mode = dynamicMode ? "dynamic" : "static";
      datasetMeta.textContent = `Source: ${source.source_label || source.source_id} | ${symbols.length} symbols | ${frequencies.join(", ")} | ${payload.adjust} | ${mode}`;
    }

    ensureWindowOption();
    ensureWindowOverlapOption();
    updateDatasetMeta();
    renderSourceButtons();
    populateBoards();
    populateSymbols();
    if (dynamicMode) {
      loadManifest();
    } else {
      setWindowToLatest(currentSeries(selectedItem()));
      renderDataStatus();
      render();
    }
  </script>
</body>
</html>
"""
