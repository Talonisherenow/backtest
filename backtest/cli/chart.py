from pathlib import Path

import typer

from backtest.charts.kline_server import serve_kline_viewer
from backtest.charts.kline_viewer import build_kline_payload, write_kline_viewer

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
