from typer.testing import CliRunner

from backtest.cli.app import app


def test_package_imports_version():
    import backtest

    assert isinstance(backtest.__version__, str)
    assert backtest.__version__


def test_cli_help_renders():
    runner = CliRunner()

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "A Share backtest research CLI" in result.output
