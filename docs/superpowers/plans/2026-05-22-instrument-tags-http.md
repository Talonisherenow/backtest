# Instrument Tags HTTP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an HTTP-only instrument catalog and tag/watchlist API backed by SQLite metadata storage.

**Architecture:** Add a focused `backtest.data.instruments` store module with Pydantic models and SQL operations. Initialize the tables from `MetadataStore`, expose thin methods on `DataSourceApi`, and wire routes in the existing stdlib HTTP server.

**Tech Stack:** Python 3.11+, SQLite, Pydantic v2, Typer-free HTTP routes, pytest.

---

## File Structure

- Create `backtest/data/instruments.py`: store models, validation, CRUD, tag membership operations.
- Modify `backtest/data/metadata.py`: enable SQLite foreign keys and initialize instrument tables.
- Modify `backtest/data_source/api.py`: add instrument/tag API methods and shared store selection.
- Modify `backtest/data_source/server.py`: add HTTP routes for instruments and tags.
- Create `tests/data/test_instrument_store.py`: store-level tests.
- Modify `tests/data_source/test_api.py`: API-level JSON serialization tests.
- Modify `tests/data_source/test_server.py`: HTTP route tests.

## Task 1: Store Schema And Instrument CRUD

**Files:**
- Create: `backtest/data/instruments.py`
- Modify: `backtest/data/metadata.py`
- Test: `tests/data/test_instrument_store.py`

- [ ] **Step 1: Write failing store CRUD tests**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/data/test_instrument_store.py::test_instrument_store_creates_lists_updates_and_deletes_instruments -q`

Expected: FAIL because `backtest.data.instruments` does not exist.

- [ ] **Step 3: Implement minimal schema and instrument CRUD**

Add `InstrumentRecord`, `InstrumentPage`, and `InstrumentStore` with these
concrete public methods:

- `create_instrument(payload: dict[str, Any]) -> InstrumentRecord`
- `get_instrument(instrument_id: str) -> InstrumentRecord`
- `update_instrument(instrument_id: str, payload: dict[str, Any]) -> InstrumentRecord`
- `delete_instrument(instrument_id: str) -> None`
- `list_instruments(source_id: str | None = None, q: str | None = None, tag: str | None = None, limit: int = 100, offset: int = 0) -> InstrumentPage`

Update `MetadataStore._init_schema()` to create the three instrument tables.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/data/test_instrument_store.py::test_instrument_store_creates_lists_updates_and_deletes_instruments -q`

Expected: PASS.

## Task 2: Tag CRUD And Memberships

**Files:**
- Modify: `backtest/data/instruments.py`
- Test: `tests/data/test_instrument_store.py`

- [ ] **Step 1: Write failing tag membership test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/data/test_instrument_store.py::test_instrument_store_manages_tags_and_memberships -q`

Expected: FAIL because tag methods are missing.

- [ ] **Step 3: Implement tag CRUD and membership methods**

Add `InstrumentTagRecord`, `InstrumentTagMembership`, `InstrumentTagMembers`,
and these concrete public methods:

- `create_tag(payload: dict[str, Any]) -> InstrumentTagRecord`
- `list_tags() -> list[InstrumentTagRecord]`
- `update_tag(tag_id: str, payload: dict[str, Any]) -> InstrumentTagRecord`
- `delete_tag(tag_id: str) -> None`
- `replace_tag_members(tag_id: str, instrument_ids: list[str]) -> InstrumentTagMembers`
- `add_tag_members(tag_id: str, instrument_ids: list[str]) -> InstrumentTagMembers`
- `remove_tag_member(tag_id: str, instrument_id: str) -> InstrumentTagMembers`

- [ ] **Step 4: Run store tests**

Run: `uv run pytest tests/data/test_instrument_store.py -q`

Expected: PASS.

## Task 3: DataSourceApi Methods

**Files:**
- Modify: `backtest/data_source/api.py`
- Test: `tests/data_source/test_api.py`

- [ ] **Step 1: Write failing API serialization test**

```python
def test_api_exposes_instrument_and_tag_methods(tmp_path: Path):
    api = _api(tmp_path)

    created = api.create_instrument(
        {
            "instrument_id": "btc/usdt",
            "symbol": "btc/usdt",
            "name": "Bitcoin",
            "source_id": "a_share",
            "metadata": {"base": "BTC"},
        }
    )
    tag = api.create_instrument_tag({"tag_id": "watchlist", "name": "Watchlist", "source_id": "a_share"})
    members = api.add_instrument_tag_members("watchlist", {"source_id": "a_share", "instrument_ids": ["BTC/USDT"]})
    filtered = api.instruments(source_id="a_share", tag="Watchlist")

    assert created["instrument_id"] == "BTC/USDT"
    assert created["metadata"] == {"base": "BTC"}
    assert tag["tag_id"] == "watchlist"
    assert members["members"][0]["instrument_id"] == "BTC/USDT"
    assert filtered["total"] == 1
    assert filtered["instruments"][0]["tags"][0]["name"] == "Watchlist"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/data_source/test_api.py::test_api_exposes_instrument_and_tag_methods -q`

Expected: FAIL because `DataSourceApi` does not expose these methods.

- [ ] **Step 3: Implement API delegation methods**

Add methods that select `InstrumentStore` from a source id, default to the first
configured source, and return values serialized through the existing `_jsonify`
helper.

- [ ] **Step 4: Run API test**

Run: `uv run pytest tests/data_source/test_api.py::test_api_exposes_instrument_and_tag_methods -q`

Expected: PASS.

## Task 4: HTTP Routes

**Files:**
- Modify: `backtest/data_source/server.py`
- Test: `tests/data_source/test_server.py`

- [ ] **Step 1: Write failing route test**

```python
def test_instrument_http_routes(tmp_path: Path):
    api = _api(tmp_path)
    server = _server_for_api(api)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, _, created = _json_request(
            base_url,
            "/api/instruments",
            method="POST",
            payload={"instrument_id": "btc/usdt", "symbol": "btc/usdt", "name": "Bitcoin", "source_id": "a_share"},
        )
        _, _, tag = _json_request(
            base_url,
            "/api/instrument-tags",
            method="POST",
            payload={"tag_id": "watchlist", "name": "Watchlist", "source_id": "a_share"},
        )
        _, _, members = _json_request(
            base_url,
            "/api/instrument-tags/watchlist/members",
            method="POST",
            payload={"source_id": "a_share", "instrument_ids": ["BTC/USDT"]},
        )
        _, _, filtered = _json_request(base_url, "/api/instruments?source_id=a_share&tag=Watchlist")
        _, _, updated = _json_request(
            base_url,
            "/api/instruments/BTC%2FUSDT?source_id=a_share",
            method="PATCH",
            payload={"name": "BTCUSDT"},
        )
        _, _, removed = _json_request(
            base_url,
            "/api/instrument-tags/watchlist/members/BTC%2FUSDT?source_id=a_share",
            method="DELETE",
        )

        assert created["instrument_id"] == "BTC/USDT"
        assert tag["name"] == "Watchlist"
        assert members["members"][0]["instrument_id"] == "BTC/USDT"
        assert filtered["total"] == 1
        assert updated["name"] == "BTCUSDT"
        assert removed["members"] == []
    finally:
        server.shutdown()
        server.server_close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/data_source/test_server.py::test_instrument_http_routes -q`

Expected: FAIL with 404 for the new routes.

- [ ] **Step 3: Implement route dispatch and path decoding**

Add GET/POST/PATCH/DELETE/PUT handling for `/api/instruments` and
`/api/instrument-tags`, using `urllib.parse.unquote` for path ids and existing
JSON/error helpers.

- [ ] **Step 4: Run route test**

Run: `uv run pytest tests/data_source/test_server.py::test_instrument_http_routes -q`

Expected: PASS.

## Task 5: Focused And Full Verification

**Files:**
- Modify docs only if route behavior differs from the design.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run pytest tests/data/test_instrument_store.py tests/data_source/test_api.py tests/data_source/test_server.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full suite**

Run:

```bash
uv run pytest -q
```

Expected: PASS, or report pre-existing failures with exact test names and errors.
