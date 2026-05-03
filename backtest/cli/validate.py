from pathlib import Path

import pandas as pd
import typer

from backtest.config.loader import load_config
from backtest.signals.providers import FileSignalProvider

app = typer.Typer(help="Validate configs and signal files")


@app.command("config")
def validate_config(
    config_path: Path = typer.Option(
        ...,
        "--config",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to backtest config YAML",
    ),
) -> None:
    """Validate a backtest config file."""
    try:
        load_config(config_path)
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("Config is valid")


@app.command("signals")
def validate_signals(
    signals_path: Path = typer.Option(
        ...,
        "--signals",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to signal CSV or Parquet file",
    ),
    symbol: list[str] | None = typer.Option(
        None,
        "--symbol",
        help="Allowed stock symbol; may be repeated",
    ),
) -> None:
    """Validate a signal file."""
    stock_pool = list(symbol) if symbol else _symbols_from_file(signals_path)
    try:
        FileSignalProvider(signals_path).load(stock_pool=stock_pool)
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("Signals are valid")


def _symbols_from_file(path: Path) -> list[str]:
    if path.suffix.lower() == ".csv":
        frame = pd.read_csv(path, usecols=["symbol"], dtype={"symbol": str})
    elif path.suffix.lower() == ".parquet":
        frame = pd.read_parquet(path, columns=["symbol"])
    else:
        return []
    return sorted(frame["symbol"].dropna().unique().tolist())
