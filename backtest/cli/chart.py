from pathlib import Path

import pandas as pd
import typer

from backtest.charts.kline_server import serve_kline_viewer
from backtest.charts.kline_service import KlineSource
from backtest.charts.kline_viewer import build_kline_payload, write_kline_viewer
from backtest.charts.strategy_results_catalog import (
    build_strategy_results_catalog_payload,
    write_strategy_results_catalog,
)
from backtest.charts.strategy_results_server import serve_strategy_results
from backtest.charts.workbench_server import serve_chart_workbench

app = typer.Typer(help="Build local charting pages from cached market data")


@app.command("viewer")
def viewer(
    bars_root: Path = typer.Option(
        Path("data/bars"),
        "--bars-root",
        file_okay=False,
        help="Root directory for cached market data",
    ),
    source_root: list[str] | None = typer.Option(
        None,
        "--source-root",
        help="Source label and bars root in label=path form; repeat for multiple sources",
    ),
    universe_path: Path | None = typer.Option(
        None,
        "--universe",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Optional universe CSV used for symbol names and board labels",
    ),
    output_path: Path = typer.Option(
        Path("runs/charts/kline_viewer.html"),
        "--output",
        help="Output HTML path",
    ),
    limit: int = typer.Option(
        300,
        "--limit",
        min=0,
        help="Maximum bars per symbol/frequency to embed; 0 embeds all cached bars",
    ),
    frequency: list[str] | None = typer.Option(
        None,
        "--frequency",
        help="Optional frequency filter; repeat for multiple frequencies",
    ),
    adjust: str = typer.Option("qfq", "--adjust", help="Adjust mode to read from cache"),
    symbols_file: Path | None = typer.Option(
        None,
        "--symbols-file",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Optional text file with one symbol per line",
    ),
    symbol: list[str] | None = typer.Option(
        None,
        "--symbol",
        help="Optional symbol filter; repeat for multiple symbols",
    ),
) -> None:
    """Build a standalone interactive K-line viewer HTML page."""
    try:
        selected_symbols = list(symbol or [])
        if symbols_file is not None:
            selected_symbols.extend(_read_symbols_file(symbols_file))
        payload = build_kline_payload(
            bars_root=bars_root,
            universe_path=universe_path,
            symbols=selected_symbols or None,
            limit=limit,
            frequency=None if not frequency else frequency[0],
            frequencies=list(frequency or []) or None,
            adjust=adjust,
            source_roots=_resolve_source_roots(bars_root, source_root),
        )
        write_kline_viewer(payload, output_path)
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Wrote K-line viewer for {len(payload['symbols'])} symbols to {output_path}")


@app.command("strategy-results")
def strategy_results(
    summary: list[Path] | None = typer.Option(
        None,
        "--summary",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Summary CSV file to include; repeat for multiple backtest batches",
    ),
    output_path: Path = typer.Option(
        Path("runs/charts/strategy_results_index.html"),
        "--output",
        help="Output HTML path",
    ),
) -> None:
    """Build a static strategy results catalog from backtest summary files."""
    try:
        frames = [pd.read_csv(path) for path in summary or []]
        payload = build_strategy_results_catalog_payload(summary_frames=frames)
        write_strategy_results_catalog(payload, output_path)
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"Wrote strategy results catalog for {payload['summary']['strategy_count']} strategies to {output_path}"
    )


@app.command("serve-results")
def serve_results(
    results_root: list[Path] | None = typer.Option(
        None,
        "--results-root",
        exists=True,
        file_okay=False,
        readable=True,
        help="Backtest result directory to scan; repeat for multiple result roots",
    ),
    bars_root: Path = typer.Option(
        Path("data/bars"),
        "--bars-root",
        exists=True,
        file_okay=False,
        readable=True,
        help="Root directory for cached market data",
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8766, "--port", min=1, max=65535, help="Bind port"),
) -> None:
    """Serve a dynamic strategy results catalog and detail viewers."""
    roots = list(results_root or [Path("runs")])
    typer.echo(f"Starting strategy results viewer at http://{host}:{port}/strategy-results")
    serve_strategy_results(results_roots=roots, bars_root=bars_root, host=host, port=port)


@app.command("serve-workbench")
def serve_workbench(
    results_root: list[Path] | None = typer.Option(
        None,
        "--results-root",
        exists=True,
        file_okay=False,
        readable=True,
        help="Backtest result directory to scan; repeat for multiple result roots",
    ),
    bars_root: Path | None = typer.Option(
        None,
        "--bars-root",
        file_okay=False,
        help="Legacy Bitget source root option; resolves data/crypto to data/crypto/bitget/bars when present",
    ),
    adjust: str | None = typer.Option(
        None,
        "--adjust",
        help="Legacy adjust mode for the Bitget source",
    ),
    bitget_bars_root: Path = typer.Option(
        Path("data/crypto/bitget/bars"),
        "--bitget-bars-root",
        file_okay=False,
        help="Root directory for cached Bitget crypto bars",
    ),
    a_share_bars_root: Path = typer.Option(
        Path("data/bars"),
        "--a-share-bars-root",
        file_okay=False,
        help="Root directory for cached A-share bars",
    ),
    a_share_universe: Path | None = typer.Option(
        Path("data/universe/a_share_all_20260504.csv"),
        "--a-share-universe",
        dir_okay=False,
        help="Optional A-share universe CSV used for symbol names and board labels",
    ),
    include_bitget: bool = typer.Option(True, "--include-bitget/--no-bitget", help="Include Bitget source"),
    include_a_share: bool = typer.Option(True, "--include-a-share/--no-a-share", help="Include A-share source"),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8767, "--port", min=1, max=65535, help="Bind port"),
    window_size: int = typer.Option(300, "--window-size", min=1, help="Initial visible K-line window"),
    data_api_base_url: str | None = typer.Option(
        None,
        "--data-api-base-url",
        help="Optional remote base URL for the K-line data API",
    ),
    data_api_token: str | None = typer.Option(
        None,
        "--data-api-token",
        envvar="BACKTEST_DATA_API_TOKEN",
        help="Optional bearer token for the remote data API",
    ),
) -> None:
    """Serve strategy results and K-line viewer from one local process."""
    try:
        kline_sources = _build_workbench_kline_sources(
            bars_root=bars_root,
            adjust=adjust,
            bitget_bars_root=bitget_bars_root,
            a_share_bars_root=a_share_bars_root,
            a_share_universe=a_share_universe,
            include_bitget=include_bitget,
            include_a_share=include_a_share,
        )
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    roots = list(results_root or [Path("runs")])
    typer.echo(f"Starting chart workbench with {len(kline_sources)} K-line sources at http://{host}:{port}")
    serve_chart_workbench(
        kline_sources=kline_sources,
        results_roots=roots,
        bars_root=a_share_bars_root,
        host=host,
        port=port,
        default_window_size=window_size,
        data_api_base_url=data_api_base_url,
        data_api_token=data_api_token,
    )


@app.command("serve")
def serve(
    bars_root: Path = typer.Option(
        Path("data/bars"),
        "--bars-root",
        file_okay=False,
        help="Root directory for cached market data",
    ),
    source_root: list[str] | None = typer.Option(
        None,
        "--source-root",
        help="Source label and bars root in label=path form; repeat for multiple sources",
    ),
    universe_path: Path | None = typer.Option(
        None,
        "--universe",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Optional universe CSV used for symbol names and board labels",
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="Host interface to bind"),
    port: int = typer.Option(8765, "--port", min=1, max=65535, help="Port to bind"),
    window_size: int = typer.Option(
        5000,
        "--window-size",
        min=1,
        help="Default number of bars loaded for each selected symbol/frequency",
    ),
    frequency: list[str] | None = typer.Option(
        None,
        "--frequency",
        help="Optional frequency filter; repeat for multiple frequencies",
    ),
    adjust: str = typer.Option("qfq", "--adjust", help="Adjust mode to read from cache"),
    symbols_file: Path | None = typer.Option(
        None,
        "--symbols-file",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Optional text file with one symbol per line",
    ),
    symbol: list[str] | None = typer.Option(
        None,
        "--symbol",
        help="Optional symbol filter; repeat for multiple symbols",
    ),
) -> None:
    """Serve a dynamic local K-line viewer that reads parquet data on demand."""
    try:
        selected_symbols = list(symbol or [])
        if symbols_file is not None:
            selected_symbols.extend(_read_symbols_file(symbols_file))
        serve_kline_viewer(
            bars_root=bars_root,
            universe_path=universe_path,
            source_roots=_resolve_source_roots(bars_root, source_root),
            host=host,
            port=port,
            default_window_size=window_size,
            frequencies=list(frequency or []) or None,
            adjust=adjust,
            symbols=selected_symbols or None,
        )
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc


def _read_symbols_file(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _parse_source_roots(values: list[str] | None) -> list[tuple[str, Path]] | None:
    if not values:
        return None

    source_roots = []
    for value in values:
        if "=" not in value:
            raise ValueError("--source-root must use label=path format")
        label, raw_path = value.split("=", 1)
        label = label.strip()
        path = Path(raw_path).expanduser()
        if not label:
            raise ValueError("--source-root label must not be empty")
        if not path.is_dir():
            raise ValueError(f"--source-root path does not exist or is not a directory: {path}")
        source_roots.append((label, path))
    return source_roots


def _resolve_source_roots(
    bars_root: Path,
    values: list[str] | None,
) -> list[tuple[str, Path]] | None:
    parsed = _parse_source_roots(values)
    if parsed is not None:
        return parsed
    return _discover_source_roots(bars_root)


def _discover_source_roots(bars_root: Path) -> list[tuple[str, Path]] | None:
    if not bars_root.is_dir():
        return None

    discovered = []
    for child in sorted(bars_root.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or child.name == "bars":
            continue
        candidate = child / "bars"
        if _looks_like_bars_root(candidate):
            discovered.append((child.name, candidate))
    return discovered or None


def _looks_like_bars_root(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any(child.is_dir() and child.name.startswith("frequency=") for child in path.iterdir())


def _build_workbench_kline_sources(
    *,
    bars_root: Path | None,
    adjust: str | None,
    bitget_bars_root: Path,
    a_share_bars_root: Path,
    a_share_universe: Path | None,
    include_bitget: bool,
    include_a_share: bool,
) -> list[KlineSource]:
    sources: list[KlineSource] = []
    if include_bitget:
        effective_bitget_root = _resolve_bars_root(bars_root) if bars_root is not None else bitget_bars_root
        _ensure_dir(effective_bitget_root)
        sources.append(KlineSource("bitget", "Bitget", effective_bitget_root, adjust=adjust or "none"))
    if include_a_share:
        _ensure_dir(a_share_bars_root)
        universe_path = a_share_universe if a_share_universe and a_share_universe.exists() else None
        sources.append(
            KlineSource(
                "a_share",
                "A-share",
                a_share_bars_root,
                adjust="qfq",
                universe_path=universe_path,
            )
        )
    if not sources:
        raise ValueError("At least one data source must be enabled")
    return sources


def _ensure_dir(path: Path) -> None:
    if not path.exists() or not path.is_dir():
        raise ValueError(f"Directory does not exist: {path}")


def _resolve_bars_root(path: Path) -> Path:
    bitget_bars = path / "bitget" / "bars"
    if bitget_bars.exists():
        return bitget_bars
    nested_bars = path / "bars"
    if nested_bars.exists():
        return nested_bars
    return path
