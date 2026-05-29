from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
from pyarrow.lib import ArrowException

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

_READ_ERRORS = (OSError, ValueError, ArrowException)
_MANIFEST_SERIES_ERRORS = (*_READ_ERRORS, KeyError)


@dataclass(frozen=True)
class KlineSource:
    source_id: str
    source_label: str
    bars_root: Path
    adjust: str = "qfq"
    universe_path: Path | None = None
    frequencies: list[str] | None = None
    symbols: list[str] | None = None


class KlineCacheService:
    """Read-only access to cached K-line parquet files for the local viewer."""

    def __init__(
        self,
        bars_root: Path | None = None,
        *,
        adjust: str = "qfq",
        universe_path: Path | None = None,
        sources: list[KlineSource] | None = None,
        source_roots: list[tuple[str, Path]] | None = None,
        frequencies: list[str] | None = None,
        symbols: list[str] | None = None,
        read_retries: int = 2,
        retry_delay_seconds: float = 0.05,
    ) -> None:
        self.read_retries = max(0, read_retries)
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)
        if sources is None:
            roots = source_roots or [("default", Path(bars_root or "data/bars"))]
            sources = [
                KlineSource(
                    source_id=_normalize_source_id(source_id),
                    source_label=_source_label(source_id),
                    bars_root=Path(source_root),
                    adjust=adjust,
                    universe_path=universe_path,
                    frequencies=frequencies,
                    symbols=symbols,
                )
                for source_id, source_root in roots
            ]
        self.sources = sources
        self._sources_by_id = {
            _normalize_source_id(source.source_id): KlineSource(
                source_id=_normalize_source_id(source.source_id),
                source_label=source.source_label,
                bars_root=Path(source.bars_root),
                adjust=source.adjust,
                universe_path=source.universe_path,
                frequencies=_sort_frequencies(source.frequencies or []) or None,
                symbols=[normalize_symbol(symbol) for symbol in source.symbols] if source.symbols else None,
            )
            for source in sources
        }
        self.sources = list(self._sources_by_id.values())
        self._metadata = {
            source.source_id: _read_universe_metadata(source.universe_path)
            if source.universe_path is not None
            else {}
            for source in self.sources
        }

    def manifest(self, *, default_window_size: int = 5000) -> dict[str, Any]:
        sources = []
        for source in self.sources:
            frequencies = self._frequencies_for(source)
            requested_symbols = source.symbols or _discover_symbols(source.bars_root, frequencies, source.adjust)
            symbols = self._manifest_symbols(source, requested_symbols, frequencies)
            if not symbols:
                continue
            sources.append(
                {
                    "source_id": source.source_id,
                    "source_label": source.source_label,
                    "frequency": frequencies[0] if len(frequencies) == 1 else "multi",
                    "frequencies": frequencies,
                    "adjust": source.adjust,
                    "symbols": symbols,
                }
            )

        primary = sources[0] if sources else None
        return {
            "mode": "dynamic",
            "source_id": primary["source_id"] if primary else "default",
            "source_label": primary["source_label"] if primary else "Cache",
            "frequency": primary["frequency"] if primary else "multi",
            "default_window_size": default_window_size,
            "default_window_overlap": 0.8,
            "frequencies": _sort_frequencies(
                [frequency for source in sources for frequency in source["frequencies"]]
            ),
            "adjust": primary["adjust"] if primary else "qfq",
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
        source = self._source(source_id)
        if source is None:
            raise ValueError(f"Unknown source: {source_id}")

        normalized_symbol = normalize_symbol(symbol)
        selected_adjust = adjust or source.adjust
        frame, paths = self._read_frame(source.bars_root, normalized_symbol, frequency, selected_adjust)
        if frame.empty:
            raise ValueError(f"No cached bars for {normalized_symbol} {frequency} {selected_adjust}")

        total = len(frame)
        size = total if limit == 0 else min(limit, total)
        max_offset = max(0, total - size)
        selected_offset = self._resolve_offset(frame, size, offset=offset, start=start, anchor=anchor)
        selected_offset = min(max(0, selected_offset), max_offset)
        window = frame.iloc[selected_offset : selected_offset + size]

        return {
            "source_id": source.source_id,
            "source_label": source.source_label,
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

    def _source(self, source_id: str | None) -> KlineSource:
        normalized = _normalize_source_id(source_id or self.sources[0].source_id)
        source = self._sources_by_id.get(normalized)
        if source is None:
            raise ValueError(f"Unknown source: {source_id}")
        return source

    def _frequencies_for(self, source: KlineSource) -> list[str]:
        if source.frequencies:
            return source.frequencies
        return _discover_frequencies(source.bars_root, source.adjust)

    def _manifest_symbols(
        self,
        source: KlineSource,
        requested_symbols: list[str],
        frequencies: list[str],
    ) -> list[dict[str, Any]]:
        items = []
        for symbol in requested_symbols:
            series = []
            for frequency in frequencies:
                try:
                    metadata = self._series_metadata(source.bars_root, symbol, frequency, source.adjust)
                except _MANIFEST_SERIES_ERRORS:
                    continue
                if metadata is not None:
                    series.append(metadata)
            if not series:
                continue
            details = self._metadata.get(source.source_id, {}).get(symbol, {})
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
        paths = self._series_paths(root, symbol, frequency, adjust)
        if not paths:
            return None
        rows, first_bar, last_bar = self._read_series_metadata(paths)
        if rows <= 0 or first_bar is None or last_bar is None:
            return None
        return {
            "frequency": frequency,
            "adjust": adjust,
            "rows": int(rows),
            "first_bar": _timestamp_label(first_bar, frequency),
            "last_bar": _timestamp_label(last_bar, frequency),
            "years": _years_from_paths(paths),
        }

    def _series_paths(
        self,
        root: Path,
        symbol: str,
        frequency: str,
        adjust: str,
    ) -> list[Path]:
        symbol_root = (
            root
            / f"frequency={frequency}"
            / f"adjust={adjust}"
            / f"symbol={safe_symbol_path(symbol)}"
        )
        return sorted(symbol_root.glob("year=*/bars.parquet"))

    def _read_series_metadata(self, paths: list[Path]) -> tuple[int, pd.Timestamp | None, pd.Timestamp | None]:
        last_error: Exception | None = None
        for attempt in range(self.read_retries + 1):
            try:
                return self._read_series_metadata_once(paths)
            except _READ_ERRORS as exc:
                last_error = exc
                if attempt >= self.read_retries:
                    break
                time.sleep(self.retry_delay_seconds)
        if last_error is not None:
            raise last_error
        return 0, None, None

    def _read_series_metadata_once(self, paths: list[Path]) -> tuple[int, pd.Timestamp | None, pd.Timestamp | None]:
        rows = 0
        first_bar: pd.Timestamp | None = None
        last_bar: pd.Timestamp | None = None
        for path in paths:
            path_rows, path_first, path_last = self._parquet_date_bounds(path)
            rows += path_rows
            if path_first is None or path_last is None:
                continue
            first_bar = path_first if first_bar is None else min(first_bar, path_first)
            last_bar = path_last if last_bar is None else max(last_bar, path_last)
        return rows, first_bar, last_bar

    def _parquet_date_bounds(self, path: Path) -> tuple[int, pd.Timestamp | None, pd.Timestamp | None]:
        metadata = pq.ParquetFile(path).metadata
        rows = int(metadata.num_rows)
        first_bar: pd.Timestamp | None = None
        last_bar: pd.Timestamp | None = None
        for row_group_index in range(metadata.num_row_groups):
            row_group = metadata.row_group(row_group_index)
            for column_index in range(row_group.num_columns):
                column = row_group.column(column_index)
                if column.path_in_schema != "date":
                    continue
                stats = column.statistics
                if stats is None or not stats.has_min_max:
                    break
                current_min = pd.Timestamp(stats.min)
                current_max = pd.Timestamp(stats.max)
                if first_bar is None or current_min < first_bar:
                    first_bar = current_min
                if last_bar is None or current_max > last_bar:
                    last_bar = current_max
                break
        if rows == 0 or (first_bar is not None and last_bar is not None):
            return rows, first_bar, last_bar

        dates = pq.read_table(path, columns=["date"]).column("date").to_pandas()
        if dates.empty:
            return rows, None, None
        return rows, pd.Timestamp(dates.min()), pd.Timestamp(dates.max())

    def _read_frame(
        self,
        root: Path,
        symbol: str,
        frequency: str,
        adjust: str,
    ) -> tuple[pd.DataFrame, list[Path]]:
        paths = self._series_paths(root, symbol, frequency, adjust)
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
            except _READ_ERRORS as exc:
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
