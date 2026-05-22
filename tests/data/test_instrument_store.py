from pathlib import Path

import pytest

from backtest.data.instruments import InstrumentStore
from backtest.data.metadata import MetadataStore


def test_instrument_store_creates_lists_updates_and_deletes_instruments(tmp_path: Path):
    store = InstrumentStore(MetadataStore(tmp_path / "metadata.sqlite"))

    created = store.create_instrument(
        {
            "instrument_id": "btc/usdt",
            "symbol": "btc/usdt",
            "name": "Bitcoin / Tether",
            "market": "crypto_spot",
            "exchange": "bitget",
            "asset_class": "crypto",
            "quote_currency": "usdt",
            "source_id": "bitget",
            "metadata": {"base": "BTC"},
        }
    )
    page = store.list_instruments(source_id="bitget", q="bitcoin")
    updated = store.update_instrument("BTC/USDT", {"name": "BTCUSDT", "metadata": {"rank": 1}})
    store.delete_instrument("BTC/USDT")

    assert created.instrument_id == "BTC/USDT"
    assert created.symbol == "BTC/USDT"
    assert created.exchange == "bitget"
    assert created.quote_currency == "USDT"
    assert created.metadata == {"base": "BTC"}
    assert page.total == 1
    assert page.instruments[0].instrument_id == "BTC/USDT"
    assert updated.name == "BTCUSDT"
    assert updated.metadata == {"rank": 1}
    with pytest.raises(ValueError, match="Unknown instrument"):
        store.get_instrument("BTC/USDT")


def test_instrument_store_manages_tags_and_memberships(tmp_path: Path):
    store = InstrumentStore(MetadataStore(tmp_path / "metadata.sqlite"))
    store.create_instrument({"instrument_id": "000001.SZ", "symbol": "000001.SZ", "name": "Ping An Bank"})
    store.create_instrument({"instrument_id": "600519.SH", "symbol": "600519.SH", "name": "Kweichow Moutai"})
    tag = store.create_tag({"tag_id": "watchlist", "name": "自选", "color": "#1f77b4"})

    replaced = store.replace_tag_members("watchlist", ["000001.SZ", "600519.SH"])
    store.remove_tag_member("watchlist", "600519.SH")
    filtered = store.list_instruments(tag="自选")
    tags = store.list_tags()

    assert tag.tag_id == "watchlist"
    assert [member.instrument_id for member in replaced.members] == ["000001.SZ", "600519.SH"]
    assert [instrument.instrument_id for instrument in filtered.instruments] == ["000001.SZ"]
    assert tags[0].member_count == 1
