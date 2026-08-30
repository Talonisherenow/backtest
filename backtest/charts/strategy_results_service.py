from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from backtest.charts.strategy_account_viewer import build_strategy_account_payload
from backtest.charts.strategy_order_drilldown_viewer import build_strategy_order_drilldown_payload
from backtest.charts.strategy_results_catalog import build_strategy_results_catalog_payload
from backtest.charts.ten_signal_attribution import attribute_ten_signal_orders
from backtest.core.symbols import normalize_symbol


class StrategyResultsService:
    def __init__(self, *, results_roots: list[Path], bars_root: Path) -> None:
        self.results_roots = [Path(root) for root in results_roots]
        self.bars_root = Path(bars_root)
        self._case_sources: dict[str, Path] = {}

    def catalog(self) -> dict[str, Any]:
        frames: list[pd.DataFrame] = []
        self._case_sources = {}
        for summary_path in self._summary_paths():
            try:
                frame = pd.read_csv(summary_path)
            except Exception:
                continue
            if not _looks_like_backtest_summary(frame):
                continue
            frames.append(frame)
            self._index_case_sources(frame, summary_path.parent)

        payload = build_strategy_results_catalog_payload(summary_frames=frames)
        for strategy in payload["strategies"]:
            for result in strategy["results"]:
                case_id = str(result.get("case_id") or "")
                result["legacy_report_href"] = ""
                if case_id in self._case_sources:
                    result["detail_href"] = f"/strategy-results/account?case_id={case_id}"
                else:
                    result["detail_href"] = ""
        return payload

    def account_payload(self, case_id: str) -> dict[str, Any]:
        run_dir = self._run_dir_for_case(case_id)
        orders = _read_table(run_dir / "orders")
        equity = _read_table(run_dir / "equity_curve")
        case_orders = _filter_case(orders, case_id)
        symbols = _symbols_for_case(case_orders)
        bars = self._bars_for_symbols(symbols)
        orders = self._attribute_orders_if_possible(orders=orders, bars=bars, symbols=symbols)
        title = _case_title(case_orders, case_id, suffix="Strategy Account Viewer")
        payload = build_strategy_account_payload(
            bars=bars,
            orders=orders,
            equity_curve=equity,
            case_id=case_id,
            title=title,
            metadata={"source_run": str(run_dir)},
        )
        payload.setdefault("links", {})["result_catalog"] = "/strategy-results"
        payload["links"]["order_drilldown"] = f"/strategy-results/drilldown?case_id={case_id}"
        return payload

    def drilldown_payload(self, case_id: str, default_symbol: str | None = None) -> dict[str, Any]:
        run_dir = self._run_dir_for_case(case_id)
        orders = _read_table(run_dir / "orders")
        equity = _read_table(run_dir / "equity_curve")
        case_orders = _filter_case(orders, case_id)
        symbols = _symbols_for_case(case_orders)
        bars = self._bars_for_symbols(symbols)
        orders = self._attribute_orders_if_possible(orders=orders, bars=bars, symbols=symbols)
        title = _case_title(case_orders, case_id, suffix="Strategy Order Drilldown")
        payload = build_strategy_order_drilldown_payload(
            bars=bars,
            orders=orders,
            equity_curve=equity,
            case_id=case_id,
            default_symbol=default_symbol,
            title=title,
            metadata={"source_run": str(run_dir)},
        )
        payload.setdefault("links", {})["strategy_account"] = f"/strategy-results/account?case_id={case_id}"
        return payload

    def _summary_paths(self) -> list[Path]:
        paths: list[Path] = []
        for root in self.results_roots:
            if root.is_file() and root.name == "summary.csv":
                paths.append(root)
            elif (root / "summary.csv").exists():
                paths.append(root / "summary.csv")
            elif root.exists():
                paths.extend(sorted(root.rglob("summary.csv")))
        return paths

    def _index_case_sources(self, frame: pd.DataFrame, run_dir: Path) -> None:
        if not (run_dir / "orders.csv").exists() and not (run_dir / "orders.parquet").exists():
            return
        if not (run_dir / "equity_curve.csv").exists() and not (run_dir / "equity_curve.parquet").exists():
            return
        for _, row in frame.iterrows():
            case_id = _runtime_case_id(row)
            if case_id:
                self._case_sources[case_id] = run_dir

    def _run_dir_for_case(self, case_id: str) -> Path:
        if not self._case_sources:
            self.catalog()
        if case_id not in self._case_sources:
            raise ValueError(f"Unknown strategy result case_id: {case_id}")
        return self._case_sources[case_id]

    def _attribute_orders_if_possible(
        self,
        *,
        orders: pd.DataFrame,
        bars: pd.DataFrame,
        symbols: list[str],
    ) -> pd.DataFrame:
        if orders.empty or bars.empty:
            return orders
        try:
            return attribute_ten_signal_orders(bars=bars, orders=orders, stock_pool=symbols)
        except Exception:
            return orders

    def _bars_for_symbols(self, symbols: list[str]) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for symbol in symbols:
            symbol_root = _symbol_root(self.bars_root, symbol)
            for path in sorted(symbol_root.glob("year=*/bars.parquet")):
                frames.append(pd.read_parquet(path))
        if not frames:
            return pd.DataFrame(
                columns=["date", "symbol", "open", "high", "low", "close", "volume", "amount"]
            )
        return pd.concat(frames, ignore_index=True)


def _looks_like_backtest_summary(frame: pd.DataFrame) -> bool:
    columns = set(frame.columns)
    return "summary" not in columns and "total_return" in columns and bool({"case", "case_id", "signal_id"} & columns)


def _runtime_case_id(row: pd.Series) -> str:
    explicit = _text(row.get("case_id"))
    if explicit:
        return explicit
    signal_id = _int_or_none(row.get("signal_id"))
    holding_days = _int_or_none(row.get("holding_days"))
    if signal_id is not None and holding_days is not None:
        return f"signal_{signal_id:02d}_hold_{holding_days}"
    return _text(row.get("case") or row.get("result_id"))


def _read_table(stem: Path) -> pd.DataFrame:
    csv_path = stem.with_suffix(".csv")
    parquet_path = stem.with_suffix(".parquet")
    if csv_path.exists():
        return pd.read_csv(csv_path)
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    raise ValueError(f"Missing result table: {csv_path} or {parquet_path}")


def _filter_case(frame: pd.DataFrame, case_id: str) -> pd.DataFrame:
    if "case_id" not in frame.columns:
        return frame.copy()
    return frame[frame["case_id"].astype(str) == case_id].copy()


def _symbols_for_case(orders: pd.DataFrame) -> list[str]:
    if orders.empty or "symbol" not in orders.columns:
        return []
    return sorted({normalize_symbol(str(symbol)) for symbol in orders["symbol"].dropna().astype(str)})


def _symbol_root(bars_root: Path, symbol: str) -> Path:
    normalized = normalize_symbol(symbol)
    direct = bars_root / f"symbol={normalized}"
    if direct.exists():
        return direct
    nested = bars_root / "frequency=1d" / "adjust=qfq" / f"symbol={normalized}"
    if nested.exists():
        return nested
    return direct


def _case_title(orders: pd.DataFrame, case_id: str, *, suffix: str) -> str:
    if not orders.empty and "case" in orders.columns:
        value = _text(orders.iloc[0].get("case"))
        if value:
            return f"{value} {suffix}"
    return f"{case_id} {suffix}"


def _text(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None
