from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DataSourceSpec:
    source_id: str
    source_label: str
    asset_class: str
    bars_root: Path
    metadata_path: Path
    adjust: str
    catalog_source: str
    universe_path: Path | None = None
    crawl_jobs: bool = True

    def public_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_label": self.source_label,
            "asset_class": self.asset_class,
            "bars": True,
            "crawl_jobs": self.crawl_jobs,
        }


@dataclass(frozen=True)
class DataSourceServerConfig:
    sources: list[DataSourceSpec]
    host: str = "127.0.0.1"
    port: int = 8768
    default_window_size: int = 300
    api_token: str | None = None
    schedule_db_path: Path = Path("data/data_source_schedules.sqlite")
    scheduler_poll_seconds: float = 1.0
    task_summary_refresh_seconds: float = 30.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "schedule_db_path", Path(self.schedule_db_path))
        if self.scheduler_poll_seconds <= 0:
            raise ValueError("scheduler_poll_seconds must be greater than 0")
        if self.task_summary_refresh_seconds <= 0:
            raise ValueError("task_summary_refresh_seconds must be greater than 0")
        if self.api_token is not None:
            token = self.api_token.strip()
            if not token:
                raise ValueError("api_token must not be blank")
            object.__setattr__(self, "api_token", token)
        seen: set[str] = set()
        for spec in self.sources:
            if spec.source_id in seen:
                raise ValueError(f"Duplicate source id: {spec.source_id}")
            seen.add(spec.source_id)
            if not spec.bars_root.exists() or not spec.bars_root.is_dir():
                raise ValueError(f"bars_root does not exist: {spec.bars_root}")

    def source(self, source_id: str) -> DataSourceSpec:
        for spec in self.sources:
            if spec.source_id == source_id:
                return spec
        raise ValueError(f"Unknown source: {source_id}")


def build_default_source_specs(
    *,
    bitget_bars_root: str | Path,
    bitget_metadata_path: str | Path,
    a_share_bars_root: str | Path,
    a_share_metadata_path: str | Path,
    include_bitget: bool = True,
    include_a_share: bool = True,
    a_share_universe: str | Path | None = None,
    a_share_catalog_source: str = "akshare",
) -> list[DataSourceSpec]:
    if not include_bitget and not include_a_share:
        raise ValueError("At least one data source must be enabled")

    specs: list[DataSourceSpec] = []
    if include_bitget:
        specs.append(
            DataSourceSpec(
                source_id="bitget",
                source_label="Bitget",
                asset_class="crypto",
                bars_root=Path(bitget_bars_root),
                metadata_path=Path(bitget_metadata_path),
                adjust="none",
                catalog_source="ccxt:bitget",
            )
        )
    if include_a_share:
        catalog_source = a_share_catalog_source.strip()
        if catalog_source not in {"akshare", "universe_csv"}:
            raise ValueError(
                "a_share_catalog_source must be one of: akshare, universe_csv"
            )
        universe_path = Path(a_share_universe) if a_share_universe is not None else None
        if universe_path is not None and not universe_path.exists():
            universe_path = None
        if catalog_source == "universe_csv" and universe_path is None:
            raise ValueError(
                "a_share_universe is required when a_share_catalog_source=universe_csv"
            )
        specs.append(
            DataSourceSpec(
                source_id="a_share",
                source_label="A-share",
                asset_class="equity",
                bars_root=Path(a_share_bars_root),
                metadata_path=Path(a_share_metadata_path),
                adjust="qfq",
                catalog_source=catalog_source,
                universe_path=universe_path,
            )
        )
    return specs
