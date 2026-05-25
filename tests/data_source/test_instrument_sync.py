from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from backtest.data.instruments import InstrumentStore
from backtest.data.metadata import MetadataStore
from backtest.data_source.config import DataSourceServerConfig, DataSourceSpec
from backtest.data_source.instrument_sync import (
    CCXTInstrumentCatalogProvider,
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


def _spec(
    tmp_path: Path,
    *,
    source_id: str = "bitget",
    catalog_source: str = "ccxt:bitget",
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
        "bitget:BTC/USDT",
        "bitget:ETH/USDT:USDT",
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

    assert items[0].instrument_id == "a_share:000001.SZ"
    assert items[0].symbol == "000001.SZ"
    assert items[0].name == "平安银行"
    assert items[0].market == "a_share"
    assert items[0].exchange == "SZ"
    assert items[0].metadata["industry"] == "bank"


def test_source_definition_maps_catalog_source_to_provider_config(tmp_path: Path):
    definition = source_definition_from_spec(_spec(tmp_path))

    assert definition.source_id == "bitget"
    assert definition.provider_type == "ccxt"
    assert definition.provider_config == {"exchange": "bitget"}
    assert definition.default_tag_id == "bitget"
    assert definition.default_tag_name == "Bitget"


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


def test_sync_service_rejects_unknown_source(tmp_path: Path):
    spec = _spec(tmp_path)
    service = InstrumentSyncService(
        config=DataSourceServerConfig(sources=[spec]),
        store_factory=lambda: InstrumentStore(MetadataStore(spec.metadata_path)),
        provider_factory=lambda definition: pytest.fail("provider should not be built"),
    )

    with pytest.raises(ValueError, match="Unknown source"):
        service.sync_source("missing")
