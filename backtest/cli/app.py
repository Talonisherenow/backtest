import typer

from backtest.cli import chart, data, data_source, run, validate

app = typer.Typer(help="A Share backtest research CLI")
app.add_typer(run.app)
app.add_typer(data.app, name="data")
app.add_typer(data_source.app, name="data-source")
app.add_typer(chart.app, name="chart")
app.add_typer(validate.app, name="validate")


@app.callback()
def root() -> None:
    """Run data ingestion, backtests, validation, and reports."""


def main() -> None:
    app()
