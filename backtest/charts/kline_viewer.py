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
) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be positive")

    normalized_symbols = [normalize_symbol(symbol) for symbol in symbols] if symbols else None
    selected_frequencies = _resolve_frequencies(bars_root, frequency, frequencies, adjust)
    requested_symbols = normalized_symbols or _discover_symbols(
        bars_root, selected_frequencies, adjust
    )
    metadata = _read_universe_metadata(universe_path)

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
                "exchange": details.get("exchange", _symbol_exchange(symbol)),
                "board": details.get("board", ""),
                "industry": details.get("industry", ""),
                "bars": series[0]["bars"],
                "series": series,
            }
        )

    if not items:
        raise ValueError("No cached K-line data found for the requested symbols")

    return {
        "frequency": selected_frequencies[0] if len(selected_frequencies) == 1 else "multi",
        "frequencies": selected_frequencies,
        "adjust": adjust,
        "limit": limit,
        "symbols": sorted(items, key=lambda item: item["symbol"]),
    }


def write_kline_viewer(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    safe_payload = payload_json.replace("</", "<\\/")
    output_path.write_text(HTML_TEMPLATE.replace("__KLINE_PAYLOAD__", safe_payload), encoding="utf-8")


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
    limited = frame.tail(limit)
    return {
        "frequency": frequency,
        "adjust": adjust,
        "rows": int(len(frame)),
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
    return ""


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
      display: grid;
      grid-template-columns: minmax(220px, 1fr) minmax(520px, 2fr);
      gap: 16px;
      align-items: end;
      padding: 16px 20px 12px;
      background: var(--surface);
      border-bottom: 1px solid var(--line);
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
      display: grid;
      grid-template-columns: minmax(150px, 0.9fr) minmax(220px, 1.4fr) minmax(130px, 0.8fr) minmax(220px, 1.2fr) auto auto;
      gap: 10px;
      align-items: end;
    }
    label {
      display: grid;
      gap: 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 600;
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
      display: inline-flex;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 6px;
      overflow: hidden;
      background: #fff;
    }
    .range button {
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
    }
    .toolbar-button:hover {
      border-color: #b8c7d6;
      background: #f8fafc;
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
      height: calc(100vh - 202px);
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
    .status-list {
      overflow: auto;
      padding: 12px;
      background: #fbfcfd;
    }
    .status-row {
      width: 100%;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      text-align: left;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--text);
      padding: 10px;
      margin-bottom: 8px;
      font: inherit;
      cursor: pointer;
    }
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
    @media (max-width: 980px) {
      .topbar { grid-template-columns: 1fr; }
      .controls { grid-template-columns: 1fr 1fr; }
      .summary { grid-template-columns: repeat(3, minmax(90px, 1fr)); }
      #chart { height: 640px; }
    }
    @media (max-width: 620px) {
      .controls { grid-template-columns: 1fr; }
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
    <div>
      <h1>K-line Cache Viewer</h1>
      <div class="subtitle" id="datasetMeta"></div>
    </div>
    <div class="controls">
      <label>Board
        <select id="boardSelect"></select>
      </label>
      <label>Symbol
        <select id="symbolSelect"></select>
      </label>
      <label>Search
        <input id="searchInput" type="search" autocomplete="off" placeholder="Code or name">
      </label>
      <label>Frequency
        <div class="range" id="frequencyButtons" aria-label="Frequency"></div>
      </label>
      <div class="range" id="rangeButtons" aria-label="Range">
        <button type="button" data-range="60">60D</button>
        <button type="button" data-range="120">120D</button>
        <button type="button" data-range="300" class="active">300D</button>
        <button type="button" data-range="all">All</button>
      </div>
      <button type="button" class="toolbar-button" id="dataStatusButton" aria-expanded="false">Data Status</button>
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
    <div class="status-list" id="dataStatusList"></div>
  </aside>
  <script>
    const payload = JSON.parse(document.getElementById("kline-payload").textContent);
    const symbols = payload.symbols || [];
    const bySymbol = new Map(symbols.map((item) => [item.symbol, item]));
    const state = {
      symbol: symbols[0]?.symbol || "",
      frequency: symbols[0]?.series?.[0]?.frequency || payload.frequency || "1d",
      board: "all",
      search: "",
      range: "300",
      drawerOpen: false,
    };

    const boardSelect = document.getElementById("boardSelect");
    const symbolSelect = document.getElementById("symbolSelect");
    const searchInput = document.getElementById("searchInput");
    const frequencyButtons = document.getElementById("frequencyButtons");
    const rangeButtons = document.getElementById("rangeButtons");
    const dataStatusButton = document.getElementById("dataStatusButton");
    const closeDrawerButton = document.getElementById("closeDrawerButton");
    const drawerBackdrop = document.getElementById("drawerBackdrop");
    const dataStatusDrawer = document.getElementById("dataStatusDrawer");
    const dataStatusList = document.getElementById("dataStatusList");
    const dataStatusMeta = document.getElementById("dataStatusMeta");
    const summary = document.getElementById("summary");
    const datasetMeta = document.getElementById("datasetMeta");
    const chart = document.getElementById("chart");

    function boardKey(item) {
      return [item.exchange || "", item.board || ""].filter(Boolean).join(" / ") || "Unknown";
    }

    function optionLabel(item) {
      return [item.symbol, item.name, boardKey(item)].filter(Boolean).join("  ");
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
      const byFrequency = seriesByFrequency(item);
      if (!byFrequency.has(state.frequency)) {
        state.frequency = seriesList(item)[0]?.frequency || "";
      }
      return byFrequency.get(state.frequency) || seriesList(item)[0] || null;
    }

    function populateBoards() {
      const boards = Array.from(new Set(symbols.map(boardKey))).sort();
      boardSelect.innerHTML = [
        `<option value="all">All boards (${symbols.length})</option>`,
        ...boards.map((board) => {
          const count = symbols.filter((item) => boardKey(item) === board).length;
          return `<option value="${escapeHtml(board)}">${escapeHtml(board)} (${count})</option>`;
        }),
      ].join("");
    }

    function filteredSymbols() {
      const query = state.search.trim().toLowerCase();
      return symbols.filter((item) => {
        const matchesBoard = state.board === "all" || boardKey(item) === state.board;
        const target = `${item.symbol} ${item.name || ""} ${item.exchange || ""} ${item.board || ""}`.toLowerCase();
        return matchesBoard && (!query || target.includes(query));
      });
    }

    function populateSymbols() {
      const visible = filteredSymbols();
      if (!visible.some((item) => item.symbol === state.symbol)) {
        state.symbol = visible[0]?.symbol || "";
      }
      symbolSelect.innerHTML = visible.map((item) => {
        const selected = item.symbol === state.symbol ? " selected" : "";
        return `<option value="${escapeHtml(item.symbol)}"${selected}>${escapeHtml(optionLabel(item))}</option>`;
      }).join("");
      populateFrequencies();
      renderDataStatus();
      render();
    }

    function populateFrequencies() {
      const item = bySymbol.get(state.symbol);
      const series = seriesList(item);
      if (!series.some((entry) => entry.frequency === state.frequency)) {
        state.frequency = series[0]?.frequency || "";
      }
      frequencyButtons.innerHTML = series.map((entry) => {
        const active = entry.frequency === state.frequency ? " active" : "";
        return `<button type="button" data-frequency="${escapeHtml(entry.frequency)}" class="${active.trim()}">${escapeHtml(entry.frequency)}</button>`;
      }).join("");
    }

    function barsForRange(series) {
      const bars = series?.bars || [];
      if (state.range === "all") {
        return bars;
      }
      return bars.slice(-Number(state.range));
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
        metric("Symbol", `${item.symbol} ${item.name || ""}`),
        metric("Frequency", series?.frequency || state.frequency),
        metric("Range", `${first.date} to ${last.date}`),
        metric("Close", fixed(last.close)),
        metric("Change", `${fixed(change)} (${fixed(changePct)}%)`),
        metric("Rows", compact(series?.rows || bars.length)),
      ].join("");
    }

    function metric(label, value) {
      return `<div class="metric"><span>${escapeHtml(label)}</span><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`;
    }

    function render() {
      const item = bySymbol.get(state.symbol);
      if (!item) {
        chart.className = "empty";
        chart.textContent = "No matching symbol";
        renderSummary(null, null, []);
        return;
      }
      const series = currentSeries(item);
      if (!series) {
        chart.className = "empty";
        chart.textContent = "No data for selected frequency";
        renderSummary(item, null, []);
        return;
      }
      chart.className = "";
      chart.textContent = "";
      if (!window.Plotly) {
        chart.className = "empty";
        chart.textContent = "Chart library failed to load";
        return;
      }
      const bars = barsForRange(series);
      renderSummary(item, series, bars);
      const x = bars.map((bar) => bar.date);
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

    function renderDataStatus() {
      const rows = symbols.flatMap((item) => {
        return seriesList(item).map((series) => ({ item, series }));
      });
      dataStatusMeta.textContent = `${symbols.length} symbols | ${rows.length} cached series`;
      if (!rows.length) {
        dataStatusList.innerHTML = `<div class="empty">No cached data</div>`;
        return;
      }
      dataStatusList.innerHTML = rows.map(({ item, series }) => {
        const active = item.symbol === state.symbol && series.frequency === state.frequency ? " active" : "";
        const years = Array.isArray(series.years) ? series.years.join(", ") : "";
        const range = [series.first_bar, series.last_bar].filter(Boolean).join(" to ");
        const details = [
          range,
          `${compact(series.rows || 0)} rows`,
          years ? `years ${years}` : "",
          series.adjust ? `adjust ${series.adjust}` : "",
        ].filter(Boolean).join(" | ");
        return `
          <button type="button" class="status-row${active}" data-symbol="${escapeHtml(item.symbol)}" data-frequency="${escapeHtml(series.frequency)}">
            <span>
              <strong>${escapeHtml(item.symbol)} ${escapeHtml(item.name || "")}</strong>
              <small>${escapeHtml(details)}</small>
            </span>
            <span class="status-pill">${escapeHtml(series.frequency)}</span>
          </button>
        `;
      }).join("");
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

    boardSelect.addEventListener("change", () => {
      state.board = boardSelect.value;
      populateSymbols();
    });
    symbolSelect.addEventListener("change", () => {
      state.symbol = symbolSelect.value;
      populateFrequencies();
      renderDataStatus();
      render();
    });
    searchInput.addEventListener("input", () => {
      state.search = searchInput.value;
      populateSymbols();
    });
    frequencyButtons.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-frequency]");
      if (!button) {
        return;
      }
      state.frequency = button.dataset.frequency;
      populateFrequencies();
      renderDataStatus();
      render();
    });
    rangeButtons.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-range]");
      if (!button) {
        return;
      }
      state.range = button.dataset.range;
      for (const child of rangeButtons.querySelectorAll("button")) {
        child.classList.toggle("active", child === button);
      }
      render();
    });
    dataStatusButton.addEventListener("click", () => toggleDataStatus());
    closeDrawerButton.addEventListener("click", () => toggleDataStatus(false));
    drawerBackdrop.addEventListener("click", () => toggleDataStatus(false));
    dataStatusList.addEventListener("click", (event) => {
      const row = event.target.closest("button[data-symbol][data-frequency]");
      if (!row) {
        return;
      }
      state.symbol = row.dataset.symbol;
      state.frequency = row.dataset.frequency;
      symbolSelect.value = state.symbol;
      populateFrequencies();
      toggleDataStatus(false);
      renderDataStatus();
      render();
    });
    window.addEventListener("resize", () => {
      if (chart.data) {
        Plotly.Plots.resize(chart);
      }
    });

    datasetMeta.textContent = `${symbols.length} symbols | ${(payload.frequencies || [payload.frequency]).join(", ")} | ${payload.adjust}`;
    populateBoards();
    populateSymbols();
  </script>
</body>
</html>
"""
