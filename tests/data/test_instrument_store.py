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


def test_instrument_store_upsert_reports_create_update_and_unchanged(tmp_path: Path):
    store = InstrumentStore(MetadataStore(tmp_path / "metadata.sqlite"))

    created = store.upsert_instrument(
        {
            "instrument_id": "bitget:btc/usdt",
            "symbol": "btc/usdt",
            "name": "Bitcoin",
            "market": "crypto_spot",
            "exchange": "bitget",
            "asset_class": "crypto",
            "quote_currency": "usdt",
            "source_id": "bitget",
            "metadata": {"base": "BTC"},
        }
    )
    unchanged = store.upsert_instrument(
        {
            "instrument_id": "BITGET:BTC/USDT",
            "symbol": "BTC/USDT",
            "name": "Bitcoin",
            "market": "crypto_spot",
            "exchange": "bitget",
            "asset_class": "crypto",
            "quote_currency": "USDT",
            "source_id": "bitget",
            "metadata": {"base": "BTC"},
        }
    )
    updated = store.upsert_instrument(
        {
            "instrument_id": "BITGET:BTC/USDT",
            "symbol": "BTC/USDT",
            "name": "Bitcoin USD Tether",
            "market": "crypto_spot",
            "exchange": "bitget",
            "asset_class": "crypto",
            "quote_currency": "USDT",
            "source_id": "bitget",
            "metadata": {"base": "BTC", "quote": "USDT"},
        }
    )

    assert created.action == "created"
    assert unchanged.action == "unchanged"
    assert updated.action == "updated"
    assert updated.record.name == "Bitcoin USD Tether"
    assert updated.record.metadata == {"base": "BTC", "quote": "USDT"}


def test_instrument_store_ensure_tag_returns_existing_tag_without_overwriting(tmp_path: Path):
    store = InstrumentStore(MetadataStore(tmp_path / "metadata.sqlite"))

    created = store.ensure_tag(
        {
            "tag_id": "bitget",
            "name": "Bitget",
            "description": "Synced from Bitget",
            "color": "#1d5fd1",
        }
    )
    existing = store.ensure_tag(
        {
            "tag_id": "bitget",
            "name": "Bitget Markets",
            "description": "New description",
            "color": "#168a5a",
        }
    )

    assert created.tag_id == "bitget"
    assert existing.tag_id == "bitget"
    assert existing.name == "Bitget"
    assert existing.description == "Synced from Bitget"
    assert existing.color == "#1d5fd1"


def test_instrument_store_upsert_partial_payload_preserves_existing_fields(tmp_path: Path):
    store = InstrumentStore(MetadataStore(tmp_path / "metadata.sqlite"))
    store.create_instrument(
        {
            "instrument_id": "BITGET:BTC/USDT",
            "symbol": "BTC/USDT",
            "name": "Bitcoin",
            "market": "crypto_spot",
            "exchange": "bitget",
            "asset_class": "crypto",
            "quote_currency": "USDT",
            "source_id": "bitget",
            "metadata": {"base": "BTC"},
        }
    )

    updated = store.upsert_instrument(
        {
            "instrument_id": "BITGET:BTC/USDT",
            "metadata": {"base": "BTC", "rank": 1},
        }
    )

    assert updated.action == "updated"
    assert updated.record.symbol == "BTC/USDT"
    assert updated.record.name == "Bitcoin"
    assert updated.record.market == "crypto_spot"
    assert updated.record.exchange == "bitget"
    assert updated.record.asset_class == "crypto"
    assert updated.record.quote_currency == "USDT"
    assert updated.record.source_id == "bitget"
    assert updated.record.metadata == {"base": "BTC", "rank": 1}


def test_instrument_store_upsert_and_ensure_tag_reraise_non_unknown_value_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    store = InstrumentStore(MetadataStore(tmp_path / "metadata.sqlite"))

    def fail_create_instrument(payload: dict[str, object]):
        pytest.fail("upsert_instrument should not create after non-unknown lookup errors")

    def fail_create_tag(payload: dict[str, object]):
        pytest.fail("ensure_tag should not create after non-unknown lookup errors")

    def raise_decode_failed(value: str):
        raise ValueError("decode failed")

    monkeypatch.setattr(store, "get_instrument", raise_decode_failed)
    monkeypatch.setattr(store, "create_instrument", fail_create_instrument)
    with pytest.raises(ValueError, match="decode failed"):
        store.upsert_instrument({"instrument_id": "BITGET:BTC/USDT"})

    monkeypatch.setattr(store, "get_tag", raise_decode_failed)
    monkeypatch.setattr(store, "create_tag", fail_create_tag)
    with pytest.raises(ValueError, match="decode failed"):
        store.ensure_tag({"tag_id": "bitget", "name": "Bitget"})
