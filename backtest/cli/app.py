import typer

from backtest.cli import run

app = typer.Typer(help="A Share backtest research CLI")
app.add_typer(run.app)


@app.callback()
def root() -> None:
    """Run data ingestion, backtests, validation, and reports."""


def main() -> None:
    app()
