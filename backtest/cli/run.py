from pathlib import Path

import typer

from backtest.config.loader import load_config
from backtest.engine import BacktestEngine

app = typer.Typer(help="Run backtests")


@app.command("run")
def run_backtest(
    config_path: Path = typer.Option(
        Path("configs/demo.yaml"),
        "--config",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to backtest config YAML",
    ),
) -> None:
    """Run a backtest from a config file."""
    config = load_config(config_path)
    try:
        run_dir = BacktestEngine(config, config_path=config_path).run()
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(str(run_dir))
