from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.core.symbols import normalize_symbol

BAR_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount"]
METADATA_COLUMNS = ["code", "name", "exchange", "board", "industry"]


def build_kline_payload(
    bars_root: Path,
    universe_path: Path | None = None,
    symbols: list[str] | None = None,
    limit: int = 300,
    frequency: str = "1d",
    adjust: str = "qfq",
) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("limit must be positive")

    normalized_symbols = [normalize_symbol(symbol) for symbol in symbols] if symbols else None
    requested_symbols = normalized_symbols or _discover_symbols(bars_root, frequency, adjust)
    metadata = _read_universe_metadata(universe_path)

    items = []
    for symbol in requested_symbols:
        bars = _read_symbol_bars(bars_root, symbol, frequency, adjust, limit)
        if not bars:
            continue
        details = metadata.get(symbol, {})
        items.append(
            {
                "symbol": symbol,
                "code": details.get("code", symbol.split(".")[0]),
                "name": details.get("name", ""),
                "exchange": details.get("exchange", symbol.split(".")[1]),
                "board": details.get("board", ""),
                "industry": details.get("industry", ""),
                "bars": bars,
            }
        )

    if not items:
        raise ValueError("No cached K-line data found for the requested symbols")

    return {
        "frequency": frequency,
        "adjust": adjust,
        "limit": limit,
        "symbols": sorted(items, key=lambda item: item["symbol"]),
    }


def write_kline_viewer(payload: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    safe_payload = payload_json.replace("</", "<\\/")
    output_path.write_text(HTML_TEMPLATE.replace("__KLINE_PAYLOAD__", safe_payload), encoding="utf-8")


def _discover_symbols(bars_root: Path, frequency: str, adjust: str) -> list[str]:
    base = bars_root / f"frequency={frequency}" / f"adjust={adjust}"
    if not base.exists():
        return []
    symbols = []
    for path in base.glob("symbol=*"):
        if path.is_dir():
            symbols.append(normalize_symbol(path.name.removeprefix("symbol=")))
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


def _read_symbol_bars(
    bars_root: Path,
    symbol: str,
    frequency: str,
    adjust: str,
    limit: int,
) -> list[dict[str, Any]]:
    symbol_root = bars_root / f"frequency={frequency}" / f"adjust={adjust}" / f"symbol={symbol}"
    paths = sorted(symbol_root.glob("year=*/bars.parquet"))
    if not paths:
        return []

    frame = pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)
    if frame.empty:
        return []

    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values("date").drop_duplicates(["date", "symbol"], keep="last").tail(limit)
    return [_bar_to_json(row) for _, row in frame[BAR_COLUMNS].iterrows()]


def _bar_to_json(row: pd.Series) -> dict[str, Any]:
    return {
        "date": pd.Timestamp(row["date"]).date().isoformat(),
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


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>A-share K-line Viewer</title>
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
      grid-template-columns: minmax(170px, 1fr) minmax(220px, 1.4fr) minmax(130px, 0.8fr) auto;
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
      <h1>A-share K-line Viewer</h1>
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
      <div class="range" id="rangeButtons" aria-label="Range">
        <button type="button" data-range="60">60D</button>
        <button type="button" data-range="120">120D</button>
        <button type="button" data-range="300" class="active">300D</button>
        <button type="button" data-range="all">All</button>
      </div>
    </div>
  </header>
  <section class="summary" id="summary"></section>
  <main>
    <div id="chart"></div>
  </main>
  <script>
    const payload = JSON.parse(document.getElementById("kline-payload").textContent);
    const symbols = payload.symbols || [];
    const bySymbol = new Map(symbols.map((item) => [item.symbol, item]));
    const state = {
      symbol: symbols[0]?.symbol || "",
      board: "all",
      search: "",
      range: "300",
    };

    const boardSelect = document.getElementById("boardSelect");
    const symbolSelect = document.getElementById("symbolSelect");
    const searchInput = document.getElementById("searchInput");
    const rangeButtons = document.getElementById("rangeButtons");
    const summary = document.getElementById("summary");
    const datasetMeta = document.getElementById("datasetMeta");
    const chart = document.getElementById("chart");

    function boardKey(item) {
      return [item.exchange || "", item.board || ""].filter(Boolean).join(" / ") || "Unknown";
    }

    function optionLabel(item) {
      return [item.symbol, item.name, boardKey(item)].filter(Boolean).join("  ");
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
      render();
    }

    function barsForRange(item) {
      const bars = item.bars || [];
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

    function renderSummary(item, bars) {
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
        metric("Board", boardKey(item)),
        metric("Range", `${first.date} to ${last.date}`),
        metric("Close", fixed(last.close)),
        metric("Change", `${fixed(change)} (${fixed(changePct)}%)`),
        metric("Volume", compact(last.volume)),
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
        renderSummary(null, []);
        return;
      }
      chart.className = "";
      chart.textContent = "";
      if (!window.Plotly) {
        chart.className = "empty";
        chart.textContent = "Chart library failed to load";
        return;
      }
      const bars = barsForRange(item);
      renderSummary(item, bars);
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
      render();
    });
    searchInput.addEventListener("input", () => {
      state.search = searchInput.value;
      populateSymbols();
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
    window.addEventListener("resize", () => {
      if (chart.data) {
        Plotly.Plots.resize(chart);
      }
    });

    datasetMeta.textContent = `${symbols.length} symbols | ${payload.frequency} | ${payload.adjust}`;
    populateBoards();
    populateSymbols();
  </script>
</body>
</html>
"""
