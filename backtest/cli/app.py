import typer

app = typer.Typer(help="A Share backtest research CLI")


@app.callback()
def root() -> None:
    """Run data ingestion, backtests, validation, and reports."""


def main() -> None:
    app()
