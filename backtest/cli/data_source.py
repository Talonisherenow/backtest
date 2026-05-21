from pathlib import Path

import typer

from backtest.cli.data import _provider_for_source
from backtest.data.catalog import DataCatalog
from backtest.data.jobs import DataSyncJobConfig, MarketDataJobRunner
from backtest.data.metadata import MetadataStore
from backtest.data.service import DataSyncService
from backtest.data.store import ParquetBarStore
from backtest.data.tasks import CrawlTaskManager
from backtest.data_source.api import DataSourceApi
from backtest.data_source.config import DataSourceServerConfig, build_default_source_specs
from backtest.data_source.jobs import DataSourceJobRegistry
from backtest.data_source.schedules import (
    DataSourceScheduleService,
    DataSourceScheduleStore,
    DataSourceScheduler,
)
from backtest.data_source.server import serve_data_source_api

app = typer.Typer(help="Serve remote market data source APIs")


@app.command("serve")
def serve(
    bitget_bars_root: Path = typer.Option(
        Path("data/crypto/bitget/bars"),
        "--bitget-bars-root",
        file_okay=False,
        help="Root directory for cached Bitget crypto bars",
    ),
    bitget_metadata: Path = typer.Option(
        Path("data/crypto/bitget/metadata.sqlite"),
        "--bitget-metadata",
        help="Metadata SQLite database for Bitget crawl tasks and catalog",
    ),
    a_share_bars_root: Path = typer.Option(
        Path("data/bars"),
        "--a-share-bars-root",
        file_okay=False,
        help="Root directory for cached A-share bars",
    ),
    a_share_metadata: Path = typer.Option(
        Path("data/metadata.sqlite"),
        "--a-share-metadata",
        help="Metadata SQLite database for A-share crawl tasks and catalog",
    ),
    a_share_universe: Path | None = typer.Option(
        Path("data/universe/a_share_all_20260504.csv"),
        "--a-share-universe",
        dir_okay=False,
        help="Optional A-share universe CSV used for symbol names and board labels",
    ),
    include_bitget: bool = typer.Option(True, "--include-bitget/--no-bitget", help="Include Bitget source"),
    include_a_share: bool = typer.Option(True, "--include-a-share/--no-a-share", help="Include A-share source"),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8768, "--port", min=1, max=65535, help="Bind port"),
    window_size: int = typer.Option(300, "--window-size", min=1, help="Default K-line window size"),
    api_token: str | None = typer.Option(
        None,
        "--api-token",
        envvar="BACKTEST_DATA_SOURCE_TOKEN",
        help="Optional bearer token required for all data-source API requests",
    ),
    schedule_db: Path = typer.Option(
        Path("data/data_source_schedules.sqlite"),
        "--schedule-db",
        help="SQLite database for data-source schedule definitions and run history",
    ),
    scheduler_poll_seconds: float = typer.Option(
        1.0,
        "--scheduler-poll-seconds",
        min=0.1,
        help="How often the in-process scheduler scans for due schedules",
    ),
    scheduler_enabled: bool = typer.Option(
        True,
        "--scheduler/--no-scheduler",
        help="Start the in-process scheduler loop",
    ),
) -> None:
    """Serve cached bars, crawl tasks, inventory, and crawl job APIs."""
    try:
        sources = build_default_source_specs(
            bitget_bars_root=bitget_bars_root,
            bitget_metadata_path=bitget_metadata,
            a_share_bars_root=a_share_bars_root,
            a_share_metadata_path=a_share_metadata,
            a_share_universe=a_share_universe,
            include_bitget=include_bitget,
            include_a_share=include_a_share,
        )
        config = DataSourceServerConfig(
            sources=sources,
            host=host,
            port=port,
            default_window_size=window_size,
            api_token=api_token,
            schedule_db_path=schedule_db,
            scheduler_poll_seconds=scheduler_poll_seconds,
        )
        api = DataSourceApi(
            config=config,
            job_registry=DataSourceJobRegistry(run_job=_run_data_job),
        )
        schedule_service = DataSourceScheduleService(
            store=DataSourceScheduleStore(config.schedule_db_path),
            server_config=config,
            submit_job=api.submit_job,
            get_job=api.job,
        )
        api.schedule_service = schedule_service
        scheduler = DataSourceScheduler(
            service=schedule_service,
            poll_seconds=config.scheduler_poll_seconds,
        )
        if scheduler_enabled:
            scheduler.start()
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Starting data source API with {len(sources)} sources at http://{host}:{port}")
    serve_data_source_api(api=api, host=host, port=port)


def _run_data_job(config: DataSyncJobConfig):
    metadata = MetadataStore(config.metadata)
    catalog = DataCatalog(metadata)
    service = DataSyncService(
        provider=_provider_for_source(
            config.source,
            config.exchange,
            page_delay_seconds=config.page_delay_seconds,
        ),
        store=ParquetBarStore(config.bars_root),
        catalog=catalog,
        tasks=CrawlTaskManager(metadata),
    )
    return MarketDataJobRunner(service=service, catalog=catalog).run(config)
