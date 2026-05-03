from pathlib import Path

import typer

from backtest.config.loader import load_config
from backtest.data.akshare_provider import AkShareProvider
from backtest.data.catalog import DataCatalog
from backtest.data.metadata import MetadataStore
from backtest.data.service import DataSyncService
from backtest.data.store import ParquetBarStore
from backtest.data.tasks import CrawlTaskManager

app = typer.Typer(help="Manage market data cache, catalog, and crawl tasks")


def _metadata_store(path: Path) -> MetadataStore:
    return MetadataStore(path)


@app.command("sync")
def sync_data(
    config_path: Path = typer.Option(
        ...,
        "--config",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to backtest config YAML",
    ),
    metadata_path: Path = typer.Option(
        Path("data/metadata.sqlite"),
        "--metadata",
        help="Path to metadata SQLite database",
    ),
    bars_root: Path = typer.Option(
        Path("data/bars"),
        "--bars-root",
        help="Root directory for cached market data",
    ),
) -> None:
    """Sync missing market data for a config."""
    try:
        config = load_config(config_path)
        if config.data.source != "akshare":
            typer.echo("Only source=akshare is supported", err=True)
            raise typer.Exit(code=1)

        metadata = _metadata_store(metadata_path)
        catalog = DataCatalog(metadata)
        service = DataSyncService(
            provider=AkShareProvider(),
            store=ParquetBarStore(bars_root),
            catalog=catalog,
            tasks=CrawlTaskManager(metadata),
        )
        service.sync(
            symbols=config.data.stock_pool.symbols,
            start_date=config.data.start_date,
            end_date=config.data.end_date,
            frequency=config.data.frequency,
            adjust=config.data.adjust,
            source=config.data.source,
        )
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("Data sync complete")


@app.command("inventory")
def inventory(
    metadata_path: Path = typer.Option(
        Path("data/metadata.sqlite"),
        "--metadata",
        help="Path to metadata SQLite database",
    ),
) -> None:
    """Print cached market data inventory."""
    records = DataCatalog(_metadata_store(metadata_path)).inventory()
    if not records:
        typer.echo("No cached data")
        return

    for record in records:
        typer.echo(
            f"{record.symbol} {record.frequency.value} {record.adjust.value} "
            f"{record.start_date} {record.end_date} rows={record.rows}"
        )


@app.command("coverage")
def coverage(
    config_path: Path = typer.Option(
        ...,
        "--config",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to backtest config YAML",
    ),
    metadata_path: Path = typer.Option(
        Path("data/metadata.sqlite"),
        "--metadata",
        help="Path to metadata SQLite database",
    ),
) -> None:
    """Print missing data ranges for a config."""
    config = load_config(config_path)
    missing_ranges = DataCatalog(_metadata_store(metadata_path)).missing_ranges(
        config.data.stock_pool.symbols,
        config.data.start_date,
        config.data.end_date,
        config.data.frequency,
        config.data.adjust,
    )
    if not missing_ranges:
        typer.echo("Data coverage complete")
        return

    for symbol, start_date, end_date in missing_ranges:
        typer.echo(f"{symbol} missing {start_date} to {end_date}")


@app.command("tasks")
def tasks(
    metadata_path: Path = typer.Option(
        Path("data/metadata.sqlite"),
        "--metadata",
        help="Path to metadata SQLite database",
    ),
) -> None:
    """Print crawl tasks."""
    records = CrawlTaskManager(_metadata_store(metadata_path)).list_tasks()
    if not records:
        typer.echo("No crawl tasks")
        return

    for record in records:
        typer.echo(f"{record.task_id} {record.symbol} {record.status} attempts={record.attempts}")


@app.command("retry")
def retry(
    failed: bool = typer.Option(
        False,
        "--failed",
        help="Queue failed crawl tasks for retry",
    ),
    metadata_path: Path = typer.Option(
        Path("data/metadata.sqlite"),
        "--metadata",
        help="Path to metadata SQLite database",
    ),
) -> None:
    """Queue failed crawl tasks for retry."""
    if not failed:
        typer.echo("Specify --failed to retry failed tasks", err=True)
        raise typer.Exit(code=1)

    manager = CrawlTaskManager(_metadata_store(metadata_path))
    records = manager.failed_tasks()
    if not records:
        typer.echo("No failed tasks")
        return

    for record in records:
        manager.mark_retrying(record.task_id)
        typer.echo(f"Queued retry for task {record.task_id}")
