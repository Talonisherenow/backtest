from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

import pandas as pd

from backtest.charts.kline_viewer import BAR_COLUMNS, _bar_to_json, _clean_text, _read_universe_metadata


FREQUENCY_ORDER = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


@dataclass(frozen=True)
class KlineSource:
    source_id: str
    source_label: str
    bars_root: Path
    adjust: str
    universe_path: Path | None = None
    frequencies: list[str] | None = None
    symbols: list[str] | None = None


class KlineCacheService:
    """Read-only access to cached K-line parquet files for the local viewer."""

    def __init__(
        self,
        bars_root: str | Path | None = None,
        *,
        adjust: str = "qfq",
        universe_path: Path | None = None,
        sources: list[KlineSource] | None = None,
        source_roots: list[tuple[str, Path]] | None = None,
        frequencies: list[str] | None = None,
        symbols: list[str] | None = None,
        read_retries: int = 1,
        retry_delay_seconds: float = 0.05,
    ) -> None:
        if sources is None:
            if source_roots is not None:
                sources = [
                    KlineSource(
                        source_id=_normalize_source_id(source_id),
                        source_label=_source_label(source_id),
                        bars_root=Path(root),
                        adjust=adjust,
                        universe_path=universe_path,
                        frequencies=frequencies,
                        symbols=symbols,
                    )
                    for source_id, root in source_roots
                ]
            else:
                root = Path(bars_root or "data/bars")
                sources = [
                    KlineSource(
                        source_id="default",
                        source_label="Cache",
                        bars_root=root,
                        adjust=adjust,
                        universe_path=universe_path,
                        frequencies=frequencies,
                        symbols=symbols,
                    )
                ]
        self.sources = sources
        self._sources_by_id = {source.source_id: source for source in sources}
        self.read_retries = read_retries
        self.retry_delay_seconds = retry_delay_seconds
        self._metadata = {
            source.source_id: _read_universe_metadata(source.universe_path)
            if source.universe_path is not None
            else {}
            for source in sources
        }

    def manifest(self, *, default_window_size: int = 300) -> dict[str, Any]:
        return {
            "mode": "dynamic",
            "default_window_size": default_window_size,
            "default_window_overlap": 0.8,
            "sources": [
                {
                    "source_id": source.source_id,
                    "source_label": source.source_label,
                    "frequency": "multi",
                    "frequencies": self._frequencies_for(source),
                    "adjust": source.adjust,
                    "symbols": self._manifest_symbols(source),
                }
                for source in self.sources
            ],
        }

    def bars(
        self,
        *,
        source_id: str,
        symbol: str,
        frequency: str,
        adjust: str | None = None,
        limit: int = 300,
        offset: int | None = None,
        start: str | None = None,
        anchor: str = "latest",
    ) -> dict[str, Any]:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        source = self._source(source_id)
        selected_adjust = adjust or source.adjust
        frame, paths = self._read_frame(source, symbol, frequency, selected_adjust)
        if frame.empty:
            raise ValueError(f"No cached bars for {symbol} {frequency} {selected_adjust}")

        total = len(frame)
        size = total if limit == 0 else min(limit, total)
        if start:
            selected_offset = self._resolve_offset(frame, start)
        elif offset is not None:
            selected_offset = max(0, min(offset, max(0, total - size)))
        elif anchor == "latest":
            selected_offset = max(0, total - size)
        else:
            selected_offset = 0

        window = frame.iloc[selected_offset : selected_offset + size]
        bars = [_bar_to_json(row) for _, row in window[BAR_COLUMNS].iterrows()]
        return {
            "source_id": source.source_id,
            "symbol": _symbol_label(symbol),
            "frequency": frequency,
            "adjust": selected_adjust,
            "rows": total,
            "loaded_rows": len(bars),
            "offset": selected_offset,
            "start_row": selected_offset,
            "end_row": selected_offset + max(len(bars) - 1, 0),
            "first_bar": _timestamp_label(frame.iloc[0]["date"]),
            "last_bar": _timestamp_label(frame.iloc[-1]["date"]),
            "window_first_bar": bars[0]["date"] if bars else "",
            "window_last_bar": bars[-1]["date"] if bars else "",
            "years": _years_from_paths(paths),
            "bars": bars,
        }

    def _source(self, source_id: str) -> KlineSource:
        source = self._sources_by_id.get(source_id)
        if source is None:
            raise ValueError(f"Unknown source: {source_id}")
        return source

    def _frequencies_for(self, source: KlineSource) -> list[str]:
        if source.frequencies:
            return _sort_frequencies(source.frequencies)
        frequencies = []
        for path in source.bars_root.glob("frequency=*"):
            if path.is_dir() and (path / f"adjust={source.adjust}").exists():
                frequencies.append(path.name.removeprefix("frequency="))
        return _sort_frequencies(frequencies)

    def _manifest_symbols(self, source: KlineSource) -> list[dict[str, Any]]:
        symbols = source.symbols or _discover_symbols(source.bars_root, self._frequencies_for(source), source.adjust)
        metadata = self._metadata.get(source.source_id, {})
        items = []
        for symbol in symbols:
            series = [
                self._series_metadata(source, symbol, frequency, source.adjust)
                for frequency in self._frequencies_for(source)
            ]
            series = [entry for entry in series if entry is not None]
            if not series:
                continue
            details = metadata.get(symbol, {})
            items.append(
                {
                    "symbol": symbol,
                    "code": details.get("code") or _symbol_code(symbol),
                    "name": details.get("name", ""),
                    "exchange": details.get("exchange") or _symbol_exchange(source),
                    "board": details.get("board") or _symbol_board(source),
                    "industry": details.get("industry", ""),
                    "series": series,
                }
            )
        return sorted(items, key=lambda item: item["symbol"])

    def _series_metadata(
        self,
        source: KlineSource,
        symbol: str,
        frequency: str,
        adjust: str,
    ) -> dict[str, Any] | None:
        frame, paths = self._read_frame(source, symbol, frequency, adjust)
        if frame.empty:
            return None
        return {
            "frequency": frequency,
            "adjust": adjust,
            "rows": len(frame),
            "first_bar": _timestamp_label(frame.iloc[0]["date"]),
            "last_bar": _timestamp_label(frame.iloc[-1]["date"]),
            "years": _years_from_paths(paths),
        }

    def _read_frame(
        self,
        source: KlineSource,
        symbol: str,
        frequency: str,
        adjust: str,
    ) -> tuple[pd.DataFrame, list[Path]]:
        paths = _bar_paths(source.bars_root, symbol, frequency, adjust)
        if not paths:
            return pd.DataFrame(columns=BAR_COLUMNS), []
        frame = self._read_paths(paths)
        if frame.empty:
            return pd.DataFrame(columns=BAR_COLUMNS), paths
        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values("date").drop_duplicates(["date", "symbol"], keep="last").reset_index(drop=True)
        return frame, paths

    def _read_paths(self, paths: list[Path]) -> pd.DataFrame:
        last_error: OSError | None = None
        for attempt in range(max(1, self.read_retries)):
            try:
                return pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)
            except OSError as exc:
                last_error = exc
                if attempt + 1 < self.read_retries:
                    time.sleep(self.retry_delay_seconds)
        if last_error is not None:
            raise last_error
        return pd.DataFrame(columns=BAR_COLUMNS)

    @staticmethod
    def _resolve_offset(frame: pd.DataFrame, start: str) -> int:
        timestamps = frame["date"].to_numpy()
        index = timestamps.searchsorted(pd.Timestamp(start).to_datetime64(), side="left")
        return int(max(0, min(index, len(frame) - 1)))


def _bar_paths(root: Path, symbol: str, frequency: str, adjust: str) -> list[Path]:
    symbol_root = root / f"frequency={frequency}" / f"adjust={adjust}" / f"symbol={_safe_symbol_path(symbol)}"
    return sorted(symbol_root.glob("year=*/bars.parquet"))


def _discover_symbols(root: Path, frequencies: list[str], adjust: str) -> list[str]:
    symbols = []
    for frequency in frequencies:
        base = root / f"frequency={frequency}" / f"adjust={adjust}"
        for path in base.glob("symbol=*"):
            if path.is_dir():
                symbols.append(_symbol_label(path.name.removeprefix("symbol=")))
    return sorted(set(symbols))


def _safe_symbol_path(symbol: str) -> str:
    return quote(symbol, safe=".")


def _symbol_label(value: str) -> str:
    return unquote(value)


def _sort_frequencies(frequencies: list[str]) -> list[str]:
    return sorted(set(frequencies), key=lambda value: (FREQUENCY_ORDER.get(value, 999999), value))


def _years_from_paths(paths: list[Path]) -> list[int]:
    years = []
    for path in paths:
        year_text = path.parent.name.removeprefix("year=")
        if year_text.isdigit():
            years.append(int(year_text))
    return sorted(set(years))


def _timestamp_label(value: object) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.time().isoformat() == "00:00:00":
        return timestamp.date().isoformat()
    return timestamp.isoformat()


def _normalize_source_id(source_id: str) -> str:
    return source_id.strip().lower().replace(" ", "_").replace("-", "_")


def _source_label(source_id: str) -> str:
    normalized = _normalize_source_id(source_id)
    if normalized == "bitget":
        return "Bitget"
    if normalized in {"a_share", "ashare", "a股"}:
        return "A-share"
    return source_id


def _symbol_code(symbol: str) -> str:
    return symbol.split(".")[0] if "." in symbol else symbol


def _symbol_exchange(source: KlineSource) -> str:
    if source.source_id in {"bitget", "crypto"}:
        return "Crypto"
    return _clean_text(source.source_label)


def _symbol_board(source: KlineSource) -> str:
    if source.source_id in {"bitget", "crypto"}:
        return "Spot"
    return ""
