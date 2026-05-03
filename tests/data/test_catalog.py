from datetime import date
from pathlib import Path

from backtest.core.contracts import CatalogRecord
from backtest.core.enums import AdjustMode, Frequency
from backtest.data.catalog import DataCatalog
from backtest.data.metadata import MetadataStore


def test_catalog_records_coverage_and_missing_ranges(tmp_path: Path):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    catalog = DataCatalog(metadata)
    catalog.upsert(
        CatalogRecord(
            symbol="000001.SZ",
            frequency=Frequency.DAILY,
            adjust=AdjustMode.QFQ,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 10),
            rows=7,
            source="fixture",
            cache_path=tmp_path / "bars.parquet",
            updated_at=metadata.now(),
        )
    )

    records = catalog.inventory()
    missing = catalog.missing_ranges(
        symbols=["000001.SZ", "600519.SH"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 15),
        frequency=Frequency.DAILY,
        adjust=AdjustMode.QFQ,
    )

    assert len(records) == 1
    assert missing == [
        ("000001.SZ", date(2025, 1, 1), date(2025, 1, 1)),
        ("000001.SZ", date(2025, 1, 11), date(2025, 1, 15)),
        ("600519.SH", date(2025, 1, 1), date(2025, 1, 15)),
    ]


def test_catalog_missing_ranges_clamps_coverage_after_window(tmp_path: Path):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    catalog = DataCatalog(metadata)
    catalog.upsert(
        CatalogRecord(
            symbol="000001.SZ",
            frequency=Frequency.DAILY,
            adjust=AdjustMode.QFQ,
            start_date=date(2025, 3, 1),
            end_date=date(2025, 3, 10),
            rows=8,
            source="fixture",
            cache_path=tmp_path / "march.parquet",
            updated_at=metadata.now(),
        )
    )

    missing = catalog.missing_ranges(
        symbols=["000001.SZ"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        frequency=Frequency.DAILY,
        adjust=AdjustMode.QFQ,
    )

    assert missing == [("000001.SZ", date(2025, 1, 1), date(2025, 1, 31))]


def test_catalog_missing_ranges_handles_adjacent_and_overlapping_coverage(tmp_path: Path):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    catalog = DataCatalog(metadata)
    catalog.upsert(
        CatalogRecord(
            symbol="000001.SZ",
            frequency=Frequency.DAILY,
            adjust=AdjustMode.QFQ,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 10),
            rows=8,
            source="fixture",
            cache_path=tmp_path / "early.parquet",
            updated_at=metadata.now(),
        )
    )
    catalog.upsert(
        CatalogRecord(
            symbol="000001.SZ",
            frequency=Frequency.DAILY,
            adjust=AdjustMode.QFQ,
            start_date=date(2025, 1, 10),
            end_date=date(2025, 1, 20),
            rows=9,
            source="fixture",
            cache_path=tmp_path / "middle.parquet",
            updated_at=metadata.now(),
        )
    )
    catalog.upsert(
        CatalogRecord(
            symbol="000001.SZ",
            frequency=Frequency.DAILY,
            adjust=AdjustMode.QFQ,
            start_date=date(2025, 1, 21),
            end_date=date(2025, 1, 31),
            rows=9,
            source="fixture",
            cache_path=tmp_path / "late.parquet",
            updated_at=metadata.now(),
        )
    )

    missing = catalog.missing_ranges(
        symbols=["000001.SZ"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        frequency=Frequency.DAILY,
        adjust=AdjustMode.QFQ,
    )

    assert missing == []


def test_catalog_missing_ranges_can_filter_by_source(tmp_path: Path):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    catalog = DataCatalog(metadata)
    catalog.upsert(
        CatalogRecord(
            symbol="000001.SZ",
            frequency=Frequency.DAILY,
            adjust=AdjustMode.QFQ,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 31),
            rows=20,
            source="fixture",
            cache_path=tmp_path / "fixture.parquet",
            updated_at=metadata.now(),
        )
    )

    missing = catalog.missing_ranges(
        symbols=["000001.SZ"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        frequency=Frequency.DAILY,
        adjust=AdjustMode.QFQ,
        source="akshare",
    )

    assert missing == [("000001.SZ", date(2025, 1, 1), date(2025, 1, 31))]
