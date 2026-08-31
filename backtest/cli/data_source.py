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
from backtest.data_source.instrument_sync import (
    InstrumentSyncScheduleService,
    InstrumentSyncScheduleStore,
    InstrumentSyncScheduler,
    InstrumentSyncService,
)
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
        help="Optional A-share universe CSV for symbol names and universe_csv catalog sync",
    ),
    a_share_catalog_source: str = typer.Option(
        "akshare",
        "--a-share-catalog-source",
        help="A-share instrument catalog: akshare (live) or universe_csv (local CSV)",
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
    task_summary_refresh_seconds: float = typer.Option(
        30.0,
        "--task-summary-refresh-seconds",
        min=1.0,
        help="How often crawl-task summary cache is refreshed from SQLite",
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
            a_share_catalog_source=a_share_catalog_source,
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
            task_summary_refresh_seconds=task_summary_refresh_seconds,
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
            resolve_symbols=api.resolve_schedule_symbols,
        )
        api.schedule_service = schedule_service
        api.instrument_sync_service = InstrumentSyncService(
            config=config,
            store_factory=lambda: api._instrument_store(None),
        )
        instrument_sync_schedule_service = InstrumentSyncScheduleService(
            store=InstrumentSyncScheduleStore(config.schedule_db_path),
            config=config,
            sync_source=lambda source_id: api.run_instrument_sync({"source_id": source_id}),
        )
        api.instrument_sync_schedule_service = instrument_sync_schedule_service
        instrument_sync_scheduler = InstrumentSyncScheduler(
            service=instrument_sync_schedule_service,
            poll_seconds=config.scheduler_poll_seconds,
        )
        scheduler = DataSourceScheduler(
            service=schedule_service,
            poll_seconds=config.scheduler_poll_seconds,
        )
        if scheduler_enabled:
            scheduler.start()
            instrument_sync_scheduler.start()
        api.task_summary_refresher.start(refresh_immediately=True)
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Starting data source API with {len(sources)} sources at http://{host}:{port}")
    serve_data_source_api(api=api, host=host, port=port)


def _run_data_job(
    config: DataSyncJobConfig,
    *,
    on_item_finished=None,
):
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
    return MarketDataJobRunner(service=service, catalog=catalog).run(
        config,
        on_item_finished=on_item_finished,
    )
