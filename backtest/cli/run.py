from pathlib import Path

import typer

from backtest.config.loader import load_config
from backtest.engine import BacktestEngine

app = typer.Typer(help="Run backtests")


@app.command("run")
def run_backtest(
    config_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="Path to backtest config YAML"),
) -> None:
    """Run a backtest from a config file."""
    config = load_config(config_path)
    run_dir = BacktestEngine(config, config_path=config_path).run()
    typer.echo(str(run_dir))
