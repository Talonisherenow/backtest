from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pandas as pd

from backtest.charts.kline_viewer import (
    BAR_COLUMNS,
    _bar_to_json,
    _discover_frequencies,
    _discover_symbols,
    _metadata_text,
    _normalize_source_id,
    _read_universe_metadata,
    _sort_frequencies,
    _source_label,
    _symbol_board,
    _symbol_code,
    _symbol_exchange,
    _timestamp_label,
    _years_from_paths,
)
from backtest.core.symbols import normalize_symbol, safe_symbol_path


class KlineCacheService:
    """Read-only access to cached K-line parquet files for the local viewer."""

    def __init__(
        self,
        bars_root: Path,
        *,
        adjust: str = "qfq",
        universe_path: Path | None = None,
        source_roots: list[tuple[str, Path]] | None = None,
        frequencies: list[str] | None = None,
        symbols: list[str] | None = None,
        read_retries: int = 2,
        retry_delay_seconds: float = 0.05,
    ) -> None:
        self.adjust = adjust
        self.metadata = _read_universe_metadata(universe_path)
        self.frequencies = _sort_frequencies(frequencies or [])
        self.symbols = [normalize_symbol(symbol) for symbol in symbols] if symbols else None
        self.read_retries = max(0, read_retries)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)

        roots = source_roots or [("default", bars_root)]
        self.source_roots = [
            (_normalize_source_id(source_id), Path(source_root))
            for source_id, source_root in roots
        ]
        self._roots_by_id = dict(self.source_roots)

    def manifest(self) -> dict[str, Any]:
        sources = []
        for source_id, root in self.source_roots:
            frequencies = self._frequencies_for(root)
            requested_symbols = self.symbols or _discover_symbols(root, frequencies, self.adjust)
            symbols = self._manifest_symbols(root, requested_symbols, frequencies)
            if not symbols:
                continue
            sources.append(
                {
                    "source_id": source_id,
                    "source_label": _source_label(source_id),
                    "frequency": frequencies[0] if len(frequencies) == 1 else "multi",
                    "frequencies": frequencies,
                    "symbols": symbols,
                }
            )

        primary = sources[0] if sources else None
        return {
            "mode": "dynamic",
            "source_id": primary["source_id"] if primary else "default",
            "source_label": primary["source_label"] if primary else "Cache",
            "frequency": primary["frequency"] if primary else "multi",
            "frequencies": _sort_frequencies(
                [frequency for source in sources for frequency in source["frequencies"]]
            ),
            "adjust": self.adjust,
            "symbols": primary["symbols"] if primary else [],
            "sources": sources,
        }

    def bars(
        self,
        *,
        symbol: str,
        frequency: str,
        source_id: str | None = None,
        adjust: str | None = None,
        limit: int = 300,
        offset: int | None = None,
        start: str | None = None,
        anchor: str | None = None,
    ) -> dict[str, Any]:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        source_id = _normalize_source_id(source_id or self.source_roots[0][0])
        root = self._roots_by_id.get(source_id)
        if root is None:
            raise ValueError(f"Unknown source: {source_id}")

        normalized_symbol = normalize_symbol(symbol)
        selected_adjust = adjust or self.adjust
        frame, paths = self._read_frame(root, normalized_symbol, frequency, selected_adjust)
        if frame.empty:
            raise ValueError(f"No cached bars for {normalized_symbol} {frequency} {selected_adjust}")

        total = len(frame)
        size = total if limit == 0 else min(limit, total)
        max_offset = max(0, total - size)
        selected_offset = self._resolve_offset(frame, size, offset=offset, start=start, anchor=anchor)
        selected_offset = min(max(0, selected_offset), max_offset)
        window = frame.iloc[selected_offset : selected_offset + size]

        return {
            "source_id": source_id,
            "source_label": _source_label(source_id),
            "symbol": normalized_symbol,
            "frequency": frequency,
            "adjust": selected_adjust,
            "rows": int(total),
            "loaded_rows": int(len(window)),
            "offset": int(selected_offset),
            "limit": int(size),
            "start_row": int(selected_offset + 1) if len(window) else 0,
            "end_row": int(selected_offset + len(window)),
            "first_bar": _timestamp_label(frame["date"].iloc[0], frequency),
            "last_bar": _timestamp_label(frame["date"].iloc[-1], frequency),
            "window_first_bar": _timestamp_label(window["date"].iloc[0], frequency)
            if len(window)
            else "",
            "window_last_bar": _timestamp_label(window["date"].iloc[-1], frequency)
            if len(window)
            else "",
            "years": _years_from_paths(paths),
            "bars": [_bar_to_json(row, frequency) for _, row in window[BAR_COLUMNS].iterrows()],
        }

    def _frequencies_for(self, root: Path) -> list[str]:
        if self.frequencies:
            return self.frequencies
        return _discover_frequencies(root, self.adjust)

    def _manifest_symbols(
        self,
        root: Path,
        requested_symbols: list[str],
        frequencies: list[str],
    ) -> list[dict[str, Any]]:
        items = []
        for symbol in requested_symbols:
            series = []
            for frequency in frequencies:
                metadata = self._series_metadata(root, symbol, frequency, self.adjust)
                if metadata is not None:
                    series.append(metadata)
            if not series:
                continue
            details = self.metadata.get(symbol, {})
            items.append(
                {
                    "symbol": symbol,
                    "code": details.get("code", _symbol_code(symbol)),
                    "name": details.get("name", ""),
                    "exchange": _metadata_text(details, "exchange", _symbol_exchange(symbol)),
                    "board": _metadata_text(details, "board", _symbol_board(symbol)),
                    "industry": details.get("industry", ""),
                    "series": series,
                }
            )
        return sorted(items, key=lambda item: item["symbol"])

    def _series_metadata(
        self,
        root: Path,
        symbol: str,
        frequency: str,
        adjust: str,
    ) -> dict[str, Any] | None:
        frame, paths = self._read_frame(root, symbol, frequency, adjust)
        if frame.empty:
            return None
        return {
            "frequency": frequency,
            "adjust": adjust,
            "rows": int(len(frame)),
            "first_bar": _timestamp_label(frame["date"].iloc[0], frequency),
            "last_bar": _timestamp_label(frame["date"].iloc[-1], frequency),
            "years": _years_from_paths(paths),
        }

    def _read_frame(
        self,
        root: Path,
        symbol: str,
        frequency: str,
        adjust: str,
    ) -> tuple[pd.DataFrame, list[Path]]:
        symbol_root = (
            root
            / f"frequency={frequency}"
            / f"adjust={adjust}"
            / f"symbol={safe_symbol_path(symbol)}"
        )
        paths = sorted(symbol_root.glob("year=*/bars.parquet"))
        if not paths:
            return pd.DataFrame(columns=BAR_COLUMNS), []

        frame = self._read_paths(paths)
        if frame.empty:
            return pd.DataFrame(columns=BAR_COLUMNS), paths

        frame = frame.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values("date").drop_duplicates(["date", "symbol"], keep="last")
        return frame.reset_index(drop=True), paths

    def _read_paths(self, paths: list[Path]) -> pd.DataFrame:
        last_error: Exception | None = None
        for attempt in range(self.read_retries + 1):
            try:
                return pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)
            except (OSError, ValueError) as exc:
                last_error = exc
                if attempt >= self.read_retries:
                    break
                time.sleep(self.retry_delay_seconds)
        if last_error is not None:
            raise last_error
        return pd.DataFrame(columns=BAR_COLUMNS)

    @staticmethod
    def _resolve_offset(
        frame: pd.DataFrame,
        size: int,
        *,
        offset: int | None,
        start: str | None,
        anchor: str | None,
    ) -> int:
        if start:
            timestamp = pd.Timestamp(start)
            return max(0, int(frame["date"].searchsorted(timestamp, side="right")) - 1)
        if offset is not None:
            return int(offset)
        if anchor == "latest" or anchor is None:
            return max(0, len(frame) - size)
        return 0
