from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from backtest.data.instruments import InstrumentStore
from backtest.data.metadata import MetadataStore
from backtest.data_source.config import DataSourceServerConfig, DataSourceSpec
from backtest.data_source.instrument_sync import (
    CCXTInstrumentCatalogProvider,
    InstrumentCatalogItem,
    InstrumentSyncScheduleService,
    InstrumentSyncScheduleStore,
    InstrumentSyncService,
    UniverseCsvInstrumentCatalogProvider,
    source_definition_from_spec,
)


class FakeExchange:
    id = "bitget"

    def load_markets(self):
        return {
            "BTC/USDT": {
                "symbol": "BTC/USDT",
                "base": "BTC",
                "quote": "USDT",
                "spot": True,
                "active": True,
                "id": "BTCUSDT",
            },
            "ETH/USDT:USDT": {
                "symbol": "ETH/USDT:USDT",
                "base": "ETH",
                "quote": "USDT",
                "swap": True,
                "active": True,
                "id": "ETHUSDT_UMCBL",
            },
            "OLD/USDT": {
                "symbol": "OLD/USDT",
                "base": "OLD",
                "quote": "USDT",
                "spot": True,
                "active": False,
                "id": "OLDUSDT",
            },
        }


class FailingUpsertStore:
    def ensure_tag(self, payload):
        return None

    def upsert_instrument(self, payload):
        raise RuntimeError("db locked")

    def add_tag_members(self, tag_id, instrument_ids):
        pytest.fail("members should not be added after upsert failure")


class FakeUpsertResult:
    def __init__(self, action: str, instrument_id: str) -> None:
        self.action = action
        self.record = type("Record", (), {"instrument_id": instrument_id})()


class MidBatchFailingStore:
    def __init__(self) -> None:
        self.upsert_calls = 0
        self.tag_member_calls: list[tuple[str, list[str]]] = []

    def ensure_tag(self, payload):
        return None

    def upsert_instrument(self, payload):
        self.upsert_calls += 1
        if self.upsert_calls == 2:
            raise RuntimeError("db locked")
        return FakeUpsertResult("created", str(payload["instrument_id"]))

    def add_tag_members(self, tag_id, instrument_ids):
        self.tag_member_calls.append((tag_id, list(instrument_ids)))


class TwoItemProvider:
    def list_instruments(self):
        return [
            InstrumentCatalogItem(
                instrument_id="BITGET:BTC/USDT",
                symbol="BTC/USDT",
                name=None,
                market="crypto_spot",
                exchange="bitget",
                asset_class="crypto",
                quote_currency="USDT",
                source_id="bitget",
                metadata={},
            ),
            InstrumentCatalogItem(
                instrument_id="BITGET:ETH/USDT:USDT",
                symbol="ETH/USDT:USDT",
                name=None,
                market="crypto_swap",
                exchange="bitget",
                asset_class="crypto",
                quote_currency="USDT",
                source_id="bitget",
                metadata={},
            ),
        ]


def _spec(
    tmp_path: Path,
    *,
    source_id: str = "bitget",
    catalog_source: str = "ccxt:bitget",
    universe_path: Path | None = None,
) -> DataSourceSpec:
    bars_root = tmp_path / source_id / "bars"
    bars_root.mkdir(parents=True)
    return DataSourceSpec(
        source_id=source_id,
        source_label="Bitget" if source_id == "bitget" else "A-share",
        asset_class="crypto" if source_id == "bitget" else "equity",
        bars_root=bars_root,
        metadata_path=tmp_path / "metadata.sqlite",
        adjust="none" if source_id == "bitget" else "qfq",
        catalog_source=catalog_source,
        universe_path=universe_path,
    )


def test_ccxt_provider_normalizes_active_markets():
    provider = CCXTInstrumentCatalogProvider(
        source_id="bitget",
        asset_class="crypto",
        exchange_id="bitget",
        exchange=FakeExchange(),
    )

    items = provider.list_instruments()

    assert [item.instrument_id for item in items] == [
        "BITGET:BTC/USDT",
        "BITGET:ETH/USDT:USDT",
    ]
    assert items[0].symbol == "BTC/USDT"
    assert items[0].market == "crypto_spot"
    assert items[0].exchange == "bitget"
    assert items[0].quote_currency == "USDT"
    assert items[0].metadata["ccxt_id"] == "BTCUSDT"
    assert items[1].market == "crypto_swap"


def test_universe_csv_provider_normalizes_a_share_rows(tmp_path: Path):
    universe = tmp_path / "a_share.csv"
    pd.DataFrame(
        [
            {
                "symbol": "000001.SZ",
                "name": "平安银行",
                "exchange": "SZ",
                "board": "main",
                "industry": "bank",
            }
        ]
    ).to_csv(universe, index=False)

    provider = UniverseCsvInstrumentCatalogProvider(
        source_id="a_share",
        asset_class="equity",
        universe_path=universe,
    )

    items = provider.list_instruments()

    assert items[0].instrument_id == "A_SHARE:000001.SZ"
    assert items[0].symbol == "000001.SZ"
    assert items[0].name == "平安银行"
    assert items[0].market == "a_share"
    assert items[0].exchange == "SZ"
    assert items[0].metadata["industry"] == "bank"


def test_universe_csv_provider_rejects_missing_file(tmp_path: Path):
    missing = tmp_path / "missing.csv"
    provider = UniverseCsvInstrumentCatalogProvider(
        source_id="a_share",
        asset_class="equity",
        universe_path=missing,
    )

    with pytest.raises(ValueError, match="Universe CSV does not exist:"):
        provider.list_instruments()


def test_source_definition_maps_catalog_source_to_provider_config(tmp_path: Path):
    definition = source_definition_from_spec(_spec(tmp_path))

    assert definition.source_id == "bitget"
    assert definition.provider_type == "ccxt"
    assert definition.provider_config == {"exchange": "bitget"}
    assert definition.default_tag_id == "bitget"
    assert definition.default_tag_name == "Bitget"


def test_source_definition_maps_akshare_universe_to_csv_provider(tmp_path: Path):
    universe = tmp_path / "a_share.csv"
    universe.write_text("symbol,name\n000001.SZ,bank\n")

    definition = source_definition_from_spec(
        _spec(
            tmp_path,
            source_id="a_share",
            catalog_source="akshare",
            universe_path=universe,
        )
    )

    assert definition.source_id == "a_share"
    assert definition.provider_type == "universe_csv"
    assert definition.provider_config == {"path": str(universe)}
    assert definition.default_tag_id == "a_share"
    assert definition.default_tag_name == "A-share"


def test_source_definition_rejects_akshare_without_universe(tmp_path: Path):
    with pytest.raises(ValueError, match="Universe path is required"):
        source_definition_from_spec(
            _spec(tmp_path, source_id="a_share", catalog_source="akshare")
        )


def test_source_definition_rejects_unsupported_catalog_source(tmp_path: Path):
    with pytest.raises(ValueError, match="Unsupported catalog source"):
        source_definition_from_spec(_spec(tmp_path, catalog_source="custom"))


def test_sync_service_upserts_instruments_and_source_tag(tmp_path: Path):
    spec = _spec(tmp_path)
    store = InstrumentStore(MetadataStore(spec.metadata_path))
    service = InstrumentSyncService(
        config=DataSourceServerConfig(sources=[spec]),
        store_factory=lambda: store,
        provider_factory=lambda definition: CCXTInstrumentCatalogProvider(
            source_id=definition.source_id,
            asset_class=definition.asset_class,
            exchange_id=str(definition.provider_config["exchange"]),
            exchange=FakeExchange(),
        ),
        now=lambda: datetime(2026, 5, 25, 9, 0, 0),
    )

    first = service.sync_source("bitget")
    second = service.sync_source("bitget")

    page = store.list_instruments(source_id="bitget")
    tags = store.list_tags()
    members = store.tag_members("bitget")
    assert first["created"] == 2
    assert first["status"] == "success"
    assert first["updated"] == 0
    assert second["created"] == 0
    assert second["unchanged"] == 2
    assert page.total == 2
    assert tags[0].tag_id == "bitget"
    assert tags[0].member_count == 2
    assert [member.instrument_id for member in members.members] == [
        "BITGET:BTC/USDT",
        "BITGET:ETH/USDT:USDT",
    ]


def test_sync_service_reraises_upsert_errors(tmp_path: Path):
    spec = _spec(tmp_path)
    service = InstrumentSyncService(
        config=DataSourceServerConfig(sources=[spec]),
        store_factory=FailingUpsertStore,
        provider_factory=lambda definition: CCXTInstrumentCatalogProvider(
            source_id=definition.source_id,
            asset_class=definition.asset_class,
            exchange_id=str(definition.provider_config["exchange"]),
            exchange=FakeExchange(),
        ),
    )

    with pytest.raises(RuntimeError, match="db locked"):
        service.sync_source("bitget")


def test_sync_service_tags_successful_items_before_mid_batch_failure(tmp_path: Path):
    spec = _spec(tmp_path)
    store = MidBatchFailingStore()
    service = InstrumentSyncService(
        config=DataSourceServerConfig(sources=[spec]),
        store_factory=lambda: store,
        provider_factory=lambda definition: TwoItemProvider(),
    )

    with pytest.raises(RuntimeError, match="db locked"):
        service.sync_source("bitget")

    assert store.tag_member_calls == [("bitget", ["BITGET:BTC/USDT"])]


def test_sync_service_rejects_unknown_source(tmp_path: Path):
    spec = _spec(tmp_path)
    service = InstrumentSyncService(
        config=DataSourceServerConfig(sources=[spec]),
        store_factory=lambda: InstrumentStore(MetadataStore(spec.metadata_path)),
        provider_factory=lambda definition: pytest.fail("provider should not be built"),
    )

    with pytest.raises(ValueError, match="Unknown source"):
        service.sync_source("missing")


def test_instrument_sync_schedule_service_creates_and_runs_schedule(tmp_path: Path):
    calls: list[str] = []
    spec = _spec(tmp_path)
    store = InstrumentSyncScheduleStore(tmp_path / "schedules.sqlite")
    service = InstrumentSyncScheduleService(
        store=store,
        config=DataSourceServerConfig(sources=[spec]),
        sync_source=lambda source_id: calls.append(source_id)
        or {
            "source_id": source_id,
            "status": "success",
            "created": 1,
            "updated": 0,
            "unchanged": 0,
            "failed": 0,
            "total": 1,
            "tag_id": source_id,
            "synced_at": "2026-05-25T09:00:00",
        },
        now=lambda: datetime(2026, 5, 25, 9, 0, 0),
    )

    created = service.create(
        {
            "name": "bitget hourly",
            "enabled": False,
            "source_id": "bitget",
            "trigger": {
                "type": "interval",
                "every": 1,
                "unit": "hours",
                "start_at": "2026-05-25T09:00:00+08:00",
            },
        }
    )
    enabled = service.enable(created.schedule_id)
    result = service.run_now(created.schedule_id)
    runs = service.runs(created.schedule_id)
    disabled = service.disable(created.schedule_id)

    assert created.status == "disabled"
    assert enabled.status == "enabled"
    assert result["source_id"] == "bitget"
    assert calls == ["bitget"]
    assert runs["runs"][0]["status"] == "success"
    assert disabled.enabled is False
