from pathlib import Path

import typer

from backtest.charts.kline_viewer import build_kline_payload, write_kline_viewer

app = typer.Typer(help="Build local charting pages from cached market data")


@app.command("viewer")
def viewer(
    bars_root: Path = typer.Option(
        Path("data/bars"),
        "--bars-root",
        exists=True,
        file_okay=False,
        readable=True,
        help="Root directory for cached market data",
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
    limit: int = typer.Option(300, "--limit", min=1, help="Maximum bars per symbol"),
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
        )
        write_kline_viewer(payload, output_path)
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Wrote K-line viewer for {len(payload['symbols'])} symbols to {output_path}")


def _read_symbols_file(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
