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

    def __post_init__(self) -> None:
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
        universe_path = Path(a_share_universe) if a_share_universe is not None else None
        specs.append(
            DataSourceSpec(
                source_id="a_share",
                source_label="A-share",
                asset_class="equity",
                bars_root=Path(a_share_bars_root),
                metadata_path=Path(a_share_metadata_path),
                adjust="qfq",
                catalog_source="akshare",
                universe_path=universe_path if universe_path and universe_path.exists() else None,
            )
        )
    return specs
