# Instrument Source Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add HTTP-managed instrument source discovery, manual sync, scheduled sync, and workbench controls for syncing instruments from CCXT exchanges and local universe files into the global instrument inventory.

**Architecture:** Keep the current instrument CRUD API shape, but route all instrument storage through one shared instrument store. Add a focused `backtest.data_source.instrument_sync` module for provider normalization, sync orchestration, and instrument-sync schedules. Expose thin methods from `DataSourceApi`, wire routes in the stdlib HTTP server, and add a modal on `/instruments` for source sync and schedules.

**Tech Stack:** Python 3, Pydantic, SQLite, stdlib `http.server`, CCXT, pandas CSV reading, existing pytest suite, workbench HTML/CSS/vanilla JavaScript.

---

## File Structure

- Modify `backtest/data/instruments.py`
  - Add `InstrumentUpsertResult`.
  - Add `InstrumentStore.upsert_instrument()`.
  - Add `InstrumentStore.ensure_tag()`.
- Create `backtest/data_source/instrument_sync.py`
  - Source definition models.
  - CCXT and universe CSV catalog providers.
  - Provider factory.
  - Sync service.
  - Schedule config/store/service/scheduler for instrument sync.
- Modify `backtest/data_source/api.py`
  - Create one shared instrument store accessor.
  - Add instrument source, sync, and schedule methods.
  - Keep existing instrument CRUD methods compatible.
- Modify `backtest/data_source/server.py`
  - Add HTTP routes for source discovery, manual sync, and schedules.
- Modify `backtest/cli/data_source.py`
  - Construct the instrument sync service and scheduler when the data-source server starts.
  - Do not add new CLI commands.
- Modify `backtest/charts/workbench_server.py`
  - Add source/sync modal and JavaScript integration on `/instruments`.
- Modify tests:
  - `tests/data/test_instrument_store.py`
  - `tests/data_source/test_instrument_sync.py`
  - `tests/data_source/test_api.py`
  - `tests/data_source/test_server.py`
  - `tests/charts/test_workbench_server.py`

Existing uncommitted pagination changes in `backtest/charts/workbench_server.py` and `tests/charts/test_workbench_server.py` are user-approved work in progress. Preserve them and build on top of them. Leave unrelated `runs/` files untouched.

---

### Task 1: Add Store Primitives For Sync

**Files:**
- Modify: `backtest/data/instruments.py`
- Test: `tests/data/test_instrument_store.py`

- [ ] **Step 1: Write the failing tests**

Append these tests to `tests/data/test_instrument_store.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/data/test_instrument_store.py::test_instrument_store_upsert_reports_create_update_and_unchanged tests/data/test_instrument_store.py::test_instrument_store_ensure_tag_returns_existing_tag_without_overwriting -q
```

Expected: FAIL with `AttributeError: 'InstrumentStore' object has no attribute 'upsert_instrument'`.

- [ ] **Step 3: Implement the store primitives**

In `backtest/data/instruments.py`, add the model near `InstrumentPage`:

```python
class InstrumentUpsertResult(BaseModel):
    action: str
    record: InstrumentRecord
```

Add these methods to `InstrumentStore` after `create_instrument()`:

```python
    def upsert_instrument(self, payload: dict[str, Any]) -> InstrumentUpsertResult:
        data = InstrumentCreate.model_validate(payload)
        try:
            existing = self.get_instrument(data.instrument_id)
        except ValueError:
            return InstrumentUpsertResult(
                action="created",
                record=self.create_instrument(data.model_dump()),
            )

        next_payload = data.model_dump()
        current_payload = {
            "symbol": existing.symbol,
            "name": existing.name,
            "market": existing.market,
            "exchange": existing.exchange,
            "asset_class": existing.asset_class,
            "quote_currency": existing.quote_currency,
            "source_id": existing.source_id,
            "metadata": existing.metadata,
        }
        candidate_payload = {
            "symbol": data.symbol,
            "name": data.name,
            "market": data.market,
            "exchange": data.exchange,
            "asset_class": data.asset_class,
            "quote_currency": data.quote_currency,
            "source_id": data.source_id,
            "metadata": data.metadata,
        }
        if candidate_payload == current_payload:
            return InstrumentUpsertResult(action="unchanged", record=existing)
        return InstrumentUpsertResult(
            action="updated",
            record=self.update_instrument(data.instrument_id, next_payload),
        )
```

Add this method after `create_tag()`:

```python
    def ensure_tag(self, payload: dict[str, Any]) -> InstrumentTagRecord:
        data = InstrumentTagCreate.model_validate(payload)
        try:
            return self.get_tag(data.tag_id)
        except ValueError:
            return self.create_tag(data.model_dump())
```

- [ ] **Step 4: Run the store tests**

Run:

```bash
uv run pytest tests/data/test_instrument_store.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/data/instruments.py tests/data/test_instrument_store.py
git commit -m "feat: add instrument store sync primitives"
```

---

### Task 2: Add Instrument Catalog Providers And Sync Service

**Files:**
- Create: `backtest/data_source/instrument_sync.py`
- Test: `tests/data_source/test_instrument_sync.py`

- [ ] **Step 1: Write the failing provider and sync tests**

Create `tests/data_source/test_instrument_sync.py`:

```python
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


def _spec(tmp_path: Path, *, source_id: str = "bitget", catalog_source: str = "ccxt:bitget") -> DataSourceSpec:
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:

```bash
uv run pytest tests/data_source/test_instrument_sync.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backtest.data_source.instrument_sync'`.

- [ ] **Step 3: Implement providers and sync service**

Create `backtest/data_source/instrument_sync.py` with these sections:

```python
from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import BaseModel, Field, field_validator, model_validator

from backtest.data.instruments import InstrumentStore
from backtest.data_source.config import DataSourceServerConfig, DataSourceSpec
from backtest.data_source.schedules import (
    DEFAULT_TIMEZONE,
    RepeatConfig,
    TriggerConfig,
    compute_next_run_at,
)
```

Add the data classes:

```python
@dataclass(frozen=True)
class InstrumentSourceDefinition:
    source_id: str
    source_label: str
    asset_class: str
    provider_type: str
    provider_config: dict[str, object]
    default_tag_id: str
    default_tag_name: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_label": self.source_label,
            "asset_class": self.asset_class,
            "provider_type": self.provider_type,
            "provider_config": self.provider_config,
            "default_tag_id": self.default_tag_id,
            "default_tag_name": self.default_tag_name,
        }


@dataclass(frozen=True)
class InstrumentCatalogItem:
    instrument_id: str
    symbol: str
    name: str | None
    market: str | None
    exchange: str | None
    asset_class: str | None
    quote_currency: str | None
    source_id: str
    metadata: dict[str, object]

    def to_instrument_payload(self) -> dict[str, object | None]:
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "name": self.name,
            "market": self.market,
            "exchange": self.exchange,
            "asset_class": self.asset_class,
            "quote_currency": self.quote_currency,
            "source_id": self.source_id,
            "metadata": self.metadata,
        }


class InstrumentCatalogProvider(Protocol):
    def list_instruments(self) -> list[InstrumentCatalogItem]:
        ...
```

Add source definition and helpers:

```python
def source_definition_from_spec(spec: DataSourceSpec) -> InstrumentSourceDefinition:
    provider_type, provider_config = _provider_from_catalog_source(spec)
    return InstrumentSourceDefinition(
        source_id=spec.source_id,
        source_label=spec.source_label,
        asset_class=spec.asset_class,
        provider_type=provider_type,
        provider_config=provider_config,
        default_tag_id=spec.source_id,
        default_tag_name=spec.source_label,
    )


def _provider_from_catalog_source(spec: DataSourceSpec) -> tuple[str, dict[str, object]]:
    if spec.catalog_source.startswith("ccxt:"):
        exchange = spec.catalog_source.split(":", 1)[1].strip()
        if not exchange:
            raise ValueError(f"Invalid catalog source: {spec.catalog_source}")
        return "ccxt", {"exchange": exchange}
    if spec.catalog_source == "akshare":
        if spec.universe_path is None:
            raise ValueError(f"Source {spec.source_id} does not have a universe file")
        return "universe_csv", {"path": str(spec.universe_path)}
    raise ValueError(f"Unsupported catalog source: {spec.catalog_source}")


def _scoped_instrument_id(source_id: str, symbol: str) -> str:
    return f"{source_id}:{symbol}".upper()
```

Add provider implementations:

```python
class CCXTInstrumentCatalogProvider:
    def __init__(
        self,
        *,
        source_id: str,
        asset_class: str,
        exchange_id: str,
        exchange: Any | None = None,
    ) -> None:
        self.source_id = source_id
        self.asset_class = asset_class
        self.exchange_id = exchange_id
        self.exchange = exchange

    def list_instruments(self) -> list[InstrumentCatalogItem]:
        exchange = self.exchange or self._build_exchange()
        markets = exchange.load_markets()
        items: list[InstrumentCatalogItem] = []
        for symbol in sorted(markets):
            market = markets[symbol]
            if market.get("active") is False:
                continue
            normalized_symbol = str(market.get("symbol") or symbol).strip().upper()
            if not normalized_symbol:
                continue
            base = _clean_optional(market.get("base"), upper=True)
            quote = _clean_optional(market.get("quote"), upper=True)
            items.append(
                InstrumentCatalogItem(
                    instrument_id=_scoped_instrument_id(self.source_id, normalized_symbol),
                    symbol=normalized_symbol,
                    name=normalized_symbol,
                    market=_ccxt_market_type(market),
                    exchange=self.exchange_id,
                    asset_class=self.asset_class,
                    quote_currency=quote,
                    source_id=self.source_id,
                    metadata={
                        "base": base,
                        "quote": quote,
                        "ccxt_id": market.get("id"),
                        "spot": bool(market.get("spot")),
                        "swap": bool(market.get("swap")),
                        "future": bool(market.get("future")),
                    },
                )
            )
        return items

    def _build_exchange(self) -> Any:
        import ccxt

        exchange_cls = getattr(ccxt, self.exchange_id, None)
        if exchange_cls is None:
            raise ValueError(f"Unsupported CCXT exchange: {self.exchange_id}")
        return exchange_cls()


class UniverseCsvInstrumentCatalogProvider:
    def __init__(self, *, source_id: str, asset_class: str, universe_path: str | Path) -> None:
        self.source_id = source_id
        self.asset_class = asset_class
        self.universe_path = Path(universe_path)

    def list_instruments(self) -> list[InstrumentCatalogItem]:
        if not self.universe_path.exists():
            raise ValueError(f"Universe file does not exist: {self.universe_path}")
        frame = pd.read_csv(self.universe_path)
        if "symbol" not in frame.columns:
            raise ValueError("Universe CSV must contain symbol column")
        items: list[InstrumentCatalogItem] = []
        for row in frame.to_dict("records"):
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            metadata = {
                key: value
                for key, value in row.items()
                if key not in {"symbol", "name", "exchange"} and pd.notna(value)
            }
            items.append(
                InstrumentCatalogItem(
                    instrument_id=_scoped_instrument_id(self.source_id, symbol),
                    symbol=symbol,
                    name=_clean_optional(row.get("name")),
                    market=self.source_id,
                    exchange=_clean_optional(row.get("exchange"), upper=True),
                    asset_class=self.asset_class,
                    quote_currency=None,
                    source_id=self.source_id,
                    metadata=metadata,
                )
            )
        return items
```

Add factory and sync service:

```python
def build_instrument_catalog_provider(
    definition: InstrumentSourceDefinition,
) -> InstrumentCatalogProvider:
    if definition.provider_type == "ccxt":
        exchange = str(definition.provider_config["exchange"])
        return CCXTInstrumentCatalogProvider(
            source_id=definition.source_id,
            asset_class=definition.asset_class,
            exchange_id=exchange,
        )
    if definition.provider_type == "universe_csv":
        path = str(definition.provider_config["path"])
        return UniverseCsvInstrumentCatalogProvider(
            source_id=definition.source_id,
            asset_class=definition.asset_class,
            universe_path=path,
        )
    raise ValueError(f"Unsupported provider_type: {definition.provider_type}")


class InstrumentSyncService:
    def __init__(
        self,
        *,
        config: DataSourceServerConfig,
        store_factory: Callable[[], InstrumentStore],
        provider_factory: Callable[[InstrumentSourceDefinition], InstrumentCatalogProvider] = build_instrument_catalog_provider,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.config = config
        self.store_factory = store_factory
        self.provider_factory = provider_factory
        self.now = now

    def sources(self) -> dict[str, list[dict[str, object]]]:
        return {"sources": [source_definition_from_spec(spec).to_dict() for spec in self.config.sources]}

    def sync_source(self, source_id: str) -> dict[str, object]:
        spec = self.config.source(source_id)
        definition = source_definition_from_spec(spec)
        provider = self.provider_factory(definition)
        items = provider.list_instruments()
        store = self.store_factory()
        store.ensure_tag(
            {
                "tag_id": definition.default_tag_id,
                "name": definition.default_tag_name,
                "description": f"Synced from {definition.source_label}",
                "color": "#1d5fd1",
            }
        )
        counts = {"created": 0, "updated": 0, "unchanged": 0}
        instrument_ids: list[str] = []
        for item in items:
            result = store.upsert_instrument(item.to_instrument_payload())
            counts[result.action] = counts.get(result.action, 0) + 1
            instrument_ids.append(result.record.instrument_id)
        if instrument_ids:
            store.add_tag_members(definition.default_tag_id, instrument_ids)
        return {
            "source_id": definition.source_id,
            "status": "success",
            "created": counts["created"],
            "updated": counts["updated"],
            "unchanged": counts["unchanged"],
            "failed": 0,
            "total": len(items),
            "tag_id": definition.default_tag_id,
            "synced_at": self.now().isoformat(),
        }
```

Add helper functions:

```python
def _ccxt_market_type(market: dict[str, Any]) -> str:
    if market.get("spot"):
        return "crypto_spot"
    if market.get("swap"):
        return "crypto_swap"
    if market.get("future"):
        return "crypto_future"
    return "crypto"


def _clean_optional(value: Any, *, upper: bool = False) -> str | None:
    if value is None or pd.isna(value):
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return normalized.upper() if upper else normalized
```

- [ ] **Step 4: Run the provider and sync tests**

Run:

```bash
uv run pytest tests/data_source/test_instrument_sync.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/data_source/instrument_sync.py tests/data_source/test_instrument_sync.py
git commit -m "feat: add instrument source sync service"
```

---

### Task 3: Add HTTP API Methods And Routes

**Files:**
- Modify: `backtest/data_source/api.py`
- Modify: `backtest/data_source/server.py`
- Test: `tests/data_source/test_api.py`
- Test: `tests/data_source/test_server.py`

- [ ] **Step 1: Write failing API tests**

Append to `tests/data_source/test_api.py`:

```python
def test_api_exposes_instrument_source_sync_methods(tmp_path: Path):
    api = _api(tmp_path)
    spec = api.config.source("a_share")
    universe = tmp_path / "a_share.csv"
    pd.DataFrame(
        [{"symbol": "000001.SZ", "name": "平安银行", "exchange": "SZ", "industry": "bank"}]
    ).to_csv(universe, index=False)
    object.__setattr__(spec, "universe_path", universe)
    api.instrument_sync_service = None

    sources = api.instrument_sources()
    result = api.run_instrument_sync({"source_id": "a_share"})
    instruments = api.instruments(source_id="a_share")
    tags = api.instrument_tags()

    assert sources["sources"][0]["provider_type"] == "universe_csv"
    assert result["source_id"] == "a_share"
    assert result["created"] == 1
    assert instruments["instruments"][0]["instrument_id"] == "A_SHARE:000001.SZ"
    assert instruments["instruments"][0]["symbol"] == "000001.SZ"
    assert tags["tags"][0]["tag_id"] == "a_share"
    assert tags["tags"][0]["member_count"] == 1
```

Add to `tests/data_source/test_server.py`:

```python
def test_instrument_source_sync_http_routes(tmp_path: Path):
    api = _api(tmp_path)
    spec = api.config.source("a_share")
    universe = tmp_path / "a_share.csv"
    pd.DataFrame(
        [{"symbol": "000001.SZ", "name": "平安银行", "exchange": "SZ", "industry": "bank"}]
    ).to_csv(universe, index=False)
    object.__setattr__(spec, "universe_path", universe)

    server = _server_for_api(api)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, _, sources = _json_request(base_url, "/api/instrument-sources")
        _, _, sync_result = _json_request(
            base_url,
            "/api/instrument-sync/run",
            method="POST",
            payload={"source_id": "a_share"},
        )
        _, _, instruments = _json_request(base_url, "/api/instruments?source_id=a_share")
        _, _, tags = _json_request(base_url, "/api/instrument-tags")

        assert sources["sources"][0]["source_id"] == "a_share"
        assert sources["sources"][0]["provider_type"] == "universe_csv"
        assert sync_result["created"] == 1
        assert instruments["total"] == 1
        assert tags["tags"][0]["tag_id"] == "a_share"
    finally:
        server.shutdown()
        server.server_close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/data_source/test_api.py::test_api_exposes_instrument_source_sync_methods tests/data_source/test_server.py::test_instrument_source_sync_http_routes -q
```

Expected: FAIL with missing `instrument_sources` or HTTP 404.

- [ ] **Step 3: Implement API methods**

In `backtest/data_source/api.py`, import:

```python
from backtest.data_source.instrument_sync import InstrumentSyncService
```

In `DataSourceApi.__init__`, add:

```python
        self.instrument_sync_service: InstrumentSyncService | None = None
```

Add these methods after `data_sources()`:

```python
    def instrument_sources(self) -> dict[str, list[dict[str, object]]]:
        return self._instrument_sync().sources()

    def run_instrument_sync(self, payload: dict[str, Any]) -> dict[str, object]:
        source_id = payload.get("source_id")
        if not source_id:
            raise ValueError("source_id is required")
        return self._instrument_sync().sync_source(str(source_id))
```

Change `_instrument_store()` so instrument CRUD uses a shared store:

```python
    def _instrument_store(self, source_id: str | None = None) -> InstrumentStore:
        if not self.config.sources:
            raise ValueError("No data sources configured")
        return InstrumentStore(self._metadata(self.config.sources[0]))
```

Add:

```python
    def _instrument_sync(self) -> InstrumentSyncService:
        if self.instrument_sync_service is None:
            self.instrument_sync_service = InstrumentSyncService(
                config=self.config,
                store_factory=lambda: self._instrument_store(None),
            )
        return self.instrument_sync_service
```

- [ ] **Step 4: Implement server routes**

In `backtest/data_source/server.py`, add GET handling before `/api/instruments`:

```python
                elif parsed.path == "/api/instrument-sources":
                    self._send_json(200, api.instrument_sources())
```

Add POST handling before `/api/instruments`:

```python
                elif parsed.path == "/api/instrument-sync/run":
                    self._send_json(200, api.run_instrument_sync(self._read_json()))
```

- [ ] **Step 5: Run API and server tests**

Run:

```bash
uv run pytest tests/data_source/test_api.py tests/data_source/test_server.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backtest/data_source/api.py backtest/data_source/server.py tests/data_source/test_api.py tests/data_source/test_server.py
git commit -m "feat: expose instrument source sync api"
```

---

### Task 4: Add Instrument Sync Schedules

**Files:**
- Modify: `backtest/data_source/instrument_sync.py`
- Modify: `backtest/data_source/api.py`
- Modify: `backtest/data_source/server.py`
- Modify: `backtest/cli/data_source.py`
- Test: `tests/data_source/test_instrument_sync.py`
- Test: `tests/data_source/test_server.py`

- [ ] **Step 1: Write failing schedule tests**

Append to `tests/data_source/test_instrument_sync.py`:

```python
from backtest.data_source.instrument_sync import (
    InstrumentSyncScheduleService,
    InstrumentSyncScheduleStore,
)


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
```

Append to `tests/data_source/test_server.py`:

```python
def test_instrument_sync_schedule_http_routes(tmp_path: Path):
    api = _api(tmp_path)
    server = _server_for_api(api)
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        _, _, created = _json_request(
            base_url,
            "/api/instrument-sync/schedules",
            method="POST",
            payload={
                "name": "a-share once",
                "enabled": False,
                "source_id": "a_share",
                "trigger": {
                    "type": "once",
                    "run_at": "2026-05-25T09:00:00+08:00",
                },
            },
        )
        schedule_id = created["schedule_id"]
        _, _, listed = _json_request(base_url, "/api/instrument-sync/schedules")
        _, _, enabled = _json_request(
            base_url,
            f"/api/instrument-sync/schedules/{schedule_id}/enable",
            method="POST",
            payload={},
        )
        _, _, disabled = _json_request(
            base_url,
            f"/api/instrument-sync/schedules/{schedule_id}/disable",
            method="POST",
            payload={},
        )
        _, _, deleted = _json_request(
            base_url,
            f"/api/instrument-sync/schedules/{schedule_id}",
            method="DELETE",
        )

        assert listed["schedules"][0]["schedule_id"] == schedule_id
        assert enabled["enabled"] is True
        assert disabled["enabled"] is False
        assert deleted == {"deleted": schedule_id}
    finally:
        server.shutdown()
        server.server_close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/data_source/test_instrument_sync.py::test_instrument_sync_schedule_service_creates_and_runs_schedule tests/data_source/test_server.py::test_instrument_sync_schedule_http_routes -q
```

Expected: FAIL with missing schedule classes or HTTP 404.

- [ ] **Step 3: Implement schedule models and store**

In `backtest/data_source/instrument_sync.py`, add:

```python
class InstrumentSyncScheduleConfig(BaseModel):
    name: str
    enabled: bool = False
    source_id: str
    trigger: TriggerConfig
    repeat: RepeatConfig = Field(default_factory=RepeatConfig)

    @field_validator("name", "source_id")
    @classmethod
    def clean_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized
```

Add dataclasses:

```python
@dataclass(frozen=True)
class InstrumentSyncScheduleSnapshot:
    schedule_id: str
    name: str
    config: InstrumentSyncScheduleConfig
    enabled: bool
    status: str
    run_count: int
    next_run_at: datetime | None
    last_run_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "schedule_id": self.schedule_id,
            "name": self.name,
            "config": self.config.model_dump(mode="json"),
            "enabled": self.enabled,
            "status": self.status,
            "run_count": self.run_count,
            "next_run_at": self.next_run_at.isoformat() if self.next_run_at else None,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True)
class InstrumentSyncScheduleRunSnapshot:
    run_id: str
    schedule_id: str
    due_at: datetime
    triggered_at: datetime
    status: str
    result_json: dict[str, Any] | None
    error: str | None
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "schedule_id": self.schedule_id,
            "due_at": self.due_at.isoformat(),
            "triggered_at": self.triggered_at.isoformat(),
            "status": self.status,
            "result": self.result_json,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
        }
```

Add `InstrumentSyncScheduleStore` using `instrument_sync_schedules` and
`instrument_sync_schedule_runs`:

```python
class InstrumentSyncScheduleStore:
    def __init__(self, path: str | Path, *, now: Callable[[], datetime] = datetime.now) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.now = now
        self._lock = threading.Lock()
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, config: InstrumentSyncScheduleConfig, *, next_run_at: datetime | None) -> InstrumentSyncScheduleSnapshot:
        now = self.now()
        with self._lock:
            schedule_id = _unique_id(self.connect, "instrument_sync_schedules", "schedule_id", now, config.name)
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO instrument_sync_schedules
                    (schedule_id, name, config_json, enabled, status, run_count, next_run_at,
                     last_run_at, last_error, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        schedule_id,
                        config.name,
                        json.dumps(config.model_dump(mode="json"), ensure_ascii=False),
                        int(config.enabled),
                        "enabled" if config.enabled else "disabled",
                        0,
                        next_run_at.isoformat() if next_run_at else None,
                        None,
                        None,
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
        return self.get(schedule_id)

    def list(self) -> list[InstrumentSyncScheduleSnapshot]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM instrument_sync_schedules ORDER BY created_at, schedule_id").fetchall()
        return [self._snapshot(row) for row in rows]

    def due(self, now: datetime) -> list[InstrumentSyncScheduleSnapshot]:
        return [
            snapshot
            for snapshot in self.list()
            if snapshot.enabled and snapshot.next_run_at is not None and snapshot.next_run_at <= now
        ]

    def get(self, schedule_id: str) -> InstrumentSyncScheduleSnapshot:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM instrument_sync_schedules WHERE schedule_id = ?",
                (schedule_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown instrument sync schedule: {schedule_id}")
        return self._snapshot(row)

    def update_config(
        self,
        schedule_id: str,
        config: InstrumentSyncScheduleConfig,
        *,
        next_run_at: datetime | None,
    ) -> InstrumentSyncScheduleSnapshot:
        now = self.now()
        with self._lock, self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE instrument_sync_schedules
                SET name = ?, config_json = ?, enabled = ?, status = ?,
                    next_run_at = ?, last_error = NULL, updated_at = ?
                WHERE schedule_id = ?
                """,
                (
                    config.name,
                    json.dumps(config.model_dump(mode="json"), ensure_ascii=False),
                    int(config.enabled),
                    "enabled" if config.enabled else "disabled",
                    next_run_at.isoformat() if next_run_at else None,
                    now.isoformat(),
                    schedule_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Unknown instrument sync schedule: {schedule_id}")
        return self.get(schedule_id)

    def update_state(
        self,
        schedule_id: str,
        *,
        enabled: bool,
        status: str,
        run_count: int,
        next_run_at: datetime | None,
        last_run_at: datetime | None,
        last_error: str | None,
    ) -> InstrumentSyncScheduleSnapshot:
        now = self.now()
        with self._lock, self.connect() as conn:
            cursor = conn.execute(
                """
                UPDATE instrument_sync_schedules
                SET enabled = ?, status = ?, run_count = ?, next_run_at = ?,
                    last_run_at = ?, last_error = ?, updated_at = ?
                WHERE schedule_id = ?
                """,
                (
                    int(enabled),
                    status,
                    run_count,
                    next_run_at.isoformat() if next_run_at else None,
                    last_run_at.isoformat() if last_run_at else None,
                    last_error,
                    now.isoformat(),
                    schedule_id,
                ),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Unknown instrument sync schedule: {schedule_id}")
        return self.get(schedule_id)

    def delete(self, schedule_id: str) -> None:
        with self._lock, self.connect() as conn:
            cursor = conn.execute(
                "DELETE FROM instrument_sync_schedules WHERE schedule_id = ?",
                (schedule_id,),
            )
            if cursor.rowcount == 0:
                raise ValueError(f"Unknown instrument sync schedule: {schedule_id}")

    def record_run(
        self,
        *,
        schedule_id: str,
        due_at: datetime,
        triggered_at: datetime,
        status: str,
        result: dict[str, Any] | None,
        error: str | None,
    ) -> InstrumentSyncScheduleRunSnapshot:
        created_at = self.now()
        with self._lock:
            run_id = _unique_id(
                self.connect,
                "instrument_sync_schedule_runs",
                "run_id",
                triggered_at,
                schedule_id,
            )
            with self.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO instrument_sync_schedule_runs
                    (run_id, schedule_id, due_at, triggered_at, status, result_json, error, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        schedule_id,
                        due_at.isoformat(),
                        triggered_at.isoformat(),
                        status,
                        json.dumps(result, ensure_ascii=False, sort_keys=True) if result is not None else None,
                        error,
                        created_at.isoformat(),
                    ),
                )
        return self.run(run_id)

    def run(self, run_id: str) -> InstrumentSyncScheduleRunSnapshot:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM instrument_sync_schedule_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown instrument sync schedule run: {run_id}")
        return self._run_snapshot(row)

    def runs(self, schedule_id: str) -> list[InstrumentSyncScheduleRunSnapshot]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM instrument_sync_schedule_runs
                WHERE schedule_id = ?
                ORDER BY triggered_at, run_id
                """,
                (schedule_id,),
            ).fetchall()
        return [self._run_snapshot(row) for row in rows]

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS instrument_sync_schedules (
                    schedule_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    run_count INTEGER NOT NULL,
                    next_run_at TEXT,
                    last_run_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS instrument_sync_schedule_runs (
                    run_id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    triggered_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )

    def _snapshot(self, row: sqlite3.Row) -> InstrumentSyncScheduleSnapshot:
        return InstrumentSyncScheduleSnapshot(
            schedule_id=row["schedule_id"],
            name=row["name"],
            config=InstrumentSyncScheduleConfig.model_validate(json.loads(row["config_json"])),
            enabled=bool(row["enabled"]),
            status=row["status"],
            run_count=int(row["run_count"]),
            next_run_at=_parse_datetime(row["next_run_at"]),
            last_run_at=_parse_datetime(row["last_run_at"]),
            last_error=row["last_error"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def _run_snapshot(self, row: sqlite3.Row) -> InstrumentSyncScheduleRunSnapshot:
        result_json = json.loads(row["result_json"]) if row["result_json"] else None
        return InstrumentSyncScheduleRunSnapshot(
            run_id=row["run_id"],
            schedule_id=row["schedule_id"],
            due_at=datetime.fromisoformat(row["due_at"]),
            triggered_at=datetime.fromisoformat(row["triggered_at"]),
            status=row["status"],
            result_json=result_json,
            error=row["error"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
```

Add helper functions below the schedule store:

```python
def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _unique_id(
    connect: Callable[[], sqlite3.Connection],
    table: str,
    column: str,
    when: datetime,
    name: str,
) -> str:
    base = f"{when:%Y%m%d%H%M%S}-{_slug(name)}"
    with connect() as conn:
        rows = conn.execute(f"SELECT {column} AS value FROM {table}").fetchall()
    existing = {row["value"] for row in rows}
    candidate = base
    counter = 2
    while candidate in existing:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def _slug(value: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    return "-".join(part for part in normalized.split("-") if part) or "schedule"


def _deep_update(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value
```

- [ ] **Step 4: Implement schedule service and scheduler**

Add:

```python
class InstrumentSyncScheduleService:
    def __init__(
        self,
        *,
        store: InstrumentSyncScheduleStore,
        config: DataSourceServerConfig,
        sync_source: Callable[[str], dict[str, object]],
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.store = store
        self.config = config
        self.sync_source = sync_source
        self.now = now

    def list(self) -> dict[str, list[dict[str, Any]]]:
        return {"schedules": [item.to_dict() for item in self.store.list()]}

    def get(self, schedule_id: str) -> InstrumentSyncScheduleSnapshot:
        return self.store.get(schedule_id)

    def create(self, payload: dict[str, Any]) -> InstrumentSyncScheduleSnapshot:
        schedule = InstrumentSyncScheduleConfig.model_validate(payload)
        self.config.source(schedule.source_id)
        next_run_at = compute_next_run_at(schedule, now=self.now(), run_count=0) if schedule.enabled else None
        return self.store.create(schedule, next_run_at=next_run_at)

    def update(self, schedule_id: str, payload: dict[str, Any]) -> InstrumentSyncScheduleSnapshot:
        current = self.store.get(schedule_id)
        merged = current.config.model_dump(mode="json")
        _deep_update(merged, payload)
        schedule = InstrumentSyncScheduleConfig.model_validate(merged)
        self.config.source(schedule.source_id)
        next_run_at = compute_next_run_at(schedule, now=self.now(), run_count=current.run_count) if schedule.enabled else None
        return self.store.update_config(schedule_id, schedule, next_run_at=next_run_at)

    def delete(self, schedule_id: str) -> dict[str, str]:
        self.store.delete(schedule_id)
        return {"deleted": schedule_id}

    def enable(self, schedule_id: str) -> InstrumentSyncScheduleSnapshot:
        current = self.store.get(schedule_id)
        config = current.config.model_copy(update={"enabled": True})
        next_run_at = compute_next_run_at(config, now=self.now(), run_count=current.run_count)
        return self.store.update_config(schedule_id, config, next_run_at=next_run_at)

    def disable(self, schedule_id: str) -> InstrumentSyncScheduleSnapshot:
        current = self.store.get(schedule_id)
        config = current.config.model_copy(update={"enabled": False})
        return self.store.update_config(schedule_id, config, next_run_at=None)

    def run_now(self, schedule_id: str) -> dict[str, object]:
        snapshot = self.store.get(schedule_id)
        return self._run(snapshot, due_at=self.now())

    def runs(self, schedule_id: str) -> dict[str, list[dict[str, Any]]]:
        self.store.get(schedule_id)
        return {"runs": [run.to_dict() for run in self.store.runs(schedule_id)]}

    def tick(self) -> None:
        now = self.now()
        for snapshot in self.store.due(now):
            try:
                self._run(snapshot, due_at=snapshot.next_run_at or now)
            except Exception:
                continue
```

Add `_run()` to `InstrumentSyncScheduleService`:

```python
    def _run(
        self,
        snapshot: InstrumentSyncScheduleSnapshot,
        *,
        due_at: datetime,
    ) -> dict[str, object]:
        triggered_at = self.now()
        try:
            result = self.sync_source(snapshot.config.source_id)
            next_count = snapshot.run_count + 1
            next_run_at = (
                compute_next_run_at(
                    snapshot.config,
                    now=triggered_at,
                    run_count=next_count,
                    after=True,
                )
                if snapshot.enabled
                else None
            )
            enabled = snapshot.enabled and next_run_at is not None
            self.store.record_run(
                schedule_id=snapshot.schedule_id,
                due_at=due_at,
                triggered_at=triggered_at,
                status="success",
                result=result,
                error=None,
            )
            self.store.update_state(
                snapshot.schedule_id,
                enabled=enabled,
                status="enabled" if enabled else ("completed" if snapshot.enabled else "disabled"),
                run_count=next_count,
                next_run_at=next_run_at,
                last_run_at=triggered_at,
                last_error=None,
            )
            return result
        except Exception as exc:
            self.store.record_run(
                schedule_id=snapshot.schedule_id,
                due_at=due_at,
                triggered_at=triggered_at,
                status="failed",
                result=None,
                error=str(exc),
            )
            next_run_at = (
                compute_next_run_at(
                    snapshot.config,
                    now=triggered_at,
                    run_count=snapshot.run_count,
                    after=True,
                )
                if snapshot.enabled
                else None
            )
            self.store.update_state(
                snapshot.schedule_id,
                enabled=snapshot.enabled and next_run_at is not None,
                status="error",
                run_count=snapshot.run_count,
                next_run_at=next_run_at,
                last_run_at=triggered_at,
                last_error=str(exc),
            )
            raise
```

Add:

```python
class InstrumentSyncScheduler:
    def __init__(self, *, service: InstrumentSyncScheduleService, poll_seconds: float) -> None:
        self.service = service
        self.poll_seconds = poll_seconds
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def tick(self) -> None:
        self.service.tick()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            finally:
                self._stop.wait(self.poll_seconds)
```

- [ ] **Step 5: Wire API and server routes**

In `backtest/data_source/api.py`, import schedule classes and add:

```python
        self.instrument_sync_schedule_service: InstrumentSyncScheduleService | None = None
```

Add methods:

```python
    def instrument_sync_schedules(self) -> dict[str, list[dict[str, Any]]]:
        return self._instrument_sync_schedules().list()

    def instrument_sync_schedule(self, schedule_id: str) -> dict[str, Any]:
        return self._instrument_sync_schedules().get(schedule_id).to_dict()

    def create_instrument_sync_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._instrument_sync_schedules().create(payload).to_dict()

    def update_instrument_sync_schedule(self, schedule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._instrument_sync_schedules().update(schedule_id, payload).to_dict()

    def delete_instrument_sync_schedule(self, schedule_id: str) -> dict[str, str]:
        return self._instrument_sync_schedules().delete(schedule_id)

    def enable_instrument_sync_schedule(self, schedule_id: str) -> dict[str, Any]:
        return self._instrument_sync_schedules().enable(schedule_id).to_dict()

    def disable_instrument_sync_schedule(self, schedule_id: str) -> dict[str, Any]:
        return self._instrument_sync_schedules().disable(schedule_id).to_dict()

    def run_instrument_sync_schedule_now(self, schedule_id: str) -> dict[str, object]:
        return self._instrument_sync_schedules().run_now(schedule_id)

    def instrument_sync_schedule_runs(self, schedule_id: str) -> dict[str, list[dict[str, Any]]]:
        return self._instrument_sync_schedules().runs(schedule_id)
```

Add `_instrument_sync_schedules()`:

```python
    def _instrument_sync_schedules(self) -> InstrumentSyncScheduleService:
        if self.instrument_sync_schedule_service is None:
            self.instrument_sync_schedule_service = InstrumentSyncScheduleService(
                store=InstrumentSyncScheduleStore(self.config.schedule_db_path),
                config=self.config,
                sync_source=lambda source_id: self.run_instrument_sync({"source_id": source_id}),
            )
        return self.instrument_sync_schedule_service
```

In `backtest/data_source/server.py`, add GET branches:

```python
                elif parsed.path == "/api/instrument-sync/schedules":
                    self._send_json(200, api.instrument_sync_schedules())
                elif parsed.path.endswith("/runs") and parsed.path.startswith("/api/instrument-sync/schedules/"):
                    self._send_json(
                        200,
                        api.instrument_sync_schedule_runs(
                            self._path_id(
                                parsed.path.removesuffix("/runs"),
                                "/api/instrument-sync/schedules/",
                            )
                        ),
                    )
                elif parsed.path.startswith("/api/instrument-sync/schedules/"):
                    self._send_json(
                        200,
                        api.instrument_sync_schedule(
                            self._path_id(parsed.path, "/api/instrument-sync/schedules/")
                        ),
                    )
```

Add POST branches:

```python
                elif parsed.path == "/api/instrument-sync/schedules":
                    self._send_json(200, api.create_instrument_sync_schedule(self._read_json()))
                elif parsed.path.endswith("/enable") and parsed.path.startswith("/api/instrument-sync/schedules/"):
                    schedule_id = self._path_id(
                        parsed.path.removesuffix("/enable"),
                        "/api/instrument-sync/schedules/",
                    )
                    self._send_json(200, api.enable_instrument_sync_schedule(schedule_id))
                elif parsed.path.endswith("/disable") and parsed.path.startswith("/api/instrument-sync/schedules/"):
                    schedule_id = self._path_id(
                        parsed.path.removesuffix("/disable"),
                        "/api/instrument-sync/schedules/",
                    )
                    self._send_json(200, api.disable_instrument_sync_schedule(schedule_id))
                elif parsed.path.endswith("/run-now") and parsed.path.startswith("/api/instrument-sync/schedules/"):
                    schedule_id = self._path_id(
                        parsed.path.removesuffix("/run-now"),
                        "/api/instrument-sync/schedules/",
                    )
                    self._send_json(200, api.run_instrument_sync_schedule_now(schedule_id))
```

Add PATCH branch before the generic instrument tag branch:

```python
                elif parsed.path.startswith("/api/instrument-sync/schedules/"):
                    self._send_json(
                        200,
                        api.update_instrument_sync_schedule(
                            self._path_id(parsed.path, "/api/instrument-sync/schedules/"),
                            self._read_json(),
                        ),
                    )
```

Add DELETE branch before `/api/instruments/`:

```python
                elif parsed.path.startswith("/api/instrument-sync/schedules/"):
                    self._send_json(
                        200,
                        api.delete_instrument_sync_schedule(
                            self._path_id(parsed.path, "/api/instrument-sync/schedules/")
                        ),
                    )
```

- [ ] **Step 6: Wire CLI startup**

In `backtest/cli/data_source.py`, import:

```python
from backtest.data_source.instrument_sync import (
    InstrumentSyncScheduleService,
    InstrumentSyncScheduleStore,
    InstrumentSyncScheduler,
    InstrumentSyncService,
)
```

After `api.schedule_service = schedule_service`, add:

```python
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
        if scheduler_enabled:
            instrument_sync_scheduler.start()
```

- [ ] **Step 7: Run schedule tests**

Run:

```bash
uv run pytest tests/data_source/test_instrument_sync.py tests/data_source/test_api.py tests/data_source/test_server.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backtest/data_source/instrument_sync.py backtest/data_source/api.py backtest/data_source/server.py backtest/cli/data_source.py tests/data_source/test_instrument_sync.py tests/data_source/test_server.py
git commit -m "feat: add instrument sync schedules"
```

---

### Task 5: Add Workbench Source Sync Modal

**Files:**
- Modify: `backtest/charts/workbench_server.py`
- Test: `tests/charts/test_workbench_server.py`

- [ ] **Step 1: Write failing HTML tests**

Extend `test_render_instrument_manager_html_uses_instrument_api()` in
`tests/charts/test_workbench_server.py` with:

```python
    assert 'id="openInstrumentSyncDialogButton"' in html
    assert ">Sources</button>" in html
    assert '<dialog id="instrumentSyncDialog"' in html
    assert 'id="instrumentSourceRows"' in html
    assert 'id="instrumentSyncScheduleRows"' in html
    assert 'id="instrumentSyncScheduleForm"' in html
    assert 'fetch(dataApiUrl("/api/instrument-sources"), instrumentRequestOptions())' in html
    assert 'fetch(dataApiUrl("/api/instrument-sync/run"), instrumentMutationOptions("POST", payload))' in html
    assert 'fetch(dataApiUrl("/api/instrument-sync/schedules"), instrumentRequestOptions())' in html
    assert 'data-sync-source-id="${escapeHtml(source.source_id)}"' in html
    assert 'data-sync-schedule-action="run"' in html
    assert "function loadInstrumentSyncState()" in html
    assert "function runInstrumentSourceSync(sourceId)" in html
    assert "function createInstrumentSyncSchedule(event)" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/charts/test_workbench_server.py::test_render_instrument_manager_html_uses_instrument_api -q
```

Expected: FAIL because the sync modal ids are missing.

- [ ] **Step 3: Add the Sources button and modal**

In `backtest/charts/workbench_server.py`, add the button beside `Workbench Home`:

```html
      <button id="openInstrumentSyncDialogButton" type="button">Sources</button>
```

Add this dialog after `instrumentCreateDialog`:

```html
  <dialog id="instrumentSyncDialog" class="modal-dialog" aria-labelledby="instrumentSyncDialogTitle">
    <div class="modal-card wide-modal">
      <div class="modal-header">
        <h2 id="instrumentSyncDialogTitle">Instrument Sources</h2>
        <button id="closeInstrumentSyncDialogButton" type="button">Close</button>
      </div>
      <div class="modal-body sync-modal-body">
        <section>
          <h3>Sources</h3>
          <div class="sync-source-list" id="instrumentSourceRows"></div>
        </section>
        <section>
          <h3>New Schedule</h3>
          <form class="form-grid" id="instrumentSyncScheduleForm">
            <input id="instrumentSyncScheduleName" type="text" autocomplete="off" placeholder="Name">
            <select id="instrumentSyncScheduleSource"></select>
            <div class="form-row">
              <input id="instrumentSyncEvery" type="number" min="1" value="1">
              <select id="instrumentSyncUnit">
                <option value="hours">hours</option>
                <option value="days">days</option>
              </select>
            </div>
            <label class="checkbox-row">
              <input id="instrumentSyncEnabled" type="checkbox">
              <span>Enabled</span>
            </label>
            <button class="primary" type="submit">Create Schedule</button>
          </form>
        </section>
        <section>
          <h3>Schedules</h3>
          <div class="sync-schedule-list" id="instrumentSyncScheduleRows"></div>
        </section>
        <div class="error" id="instrumentSyncError"></div>
      </div>
    </div>
  </dialog>
```

- [ ] **Step 4: Add CSS for compact sync rows**

Add CSS next to the existing modal styles:

```css
    .wide-modal { width: min(920px, calc(100vw - 32px)); }
    .sync-modal-body { gap: 18px; }
    .sync-source-list,
    .sync-schedule-list {
      display: grid;
      gap: 8px;
    }
    .sync-row {
      align-items: center;
      border: 1px solid var(--border);
      border-radius: 8px;
      display: grid;
      gap: 10px;
      grid-template-columns: minmax(0, 1fr) auto;
      padding: 10px 12px;
    }
    .sync-row-title {
      color: var(--text);
      font-weight: 800;
    }
    .sync-row-meta {
      color: var(--muted);
      font-size: 13px;
      margin-top: 2px;
    }
```

- [ ] **Step 5: Add JavaScript state, rendering, and actions**

Add state:

```javascript
      syncSources: [],
      syncSchedules: [],
      syncMessage: "",
```

Add functions:

```javascript
    async function loadInstrumentSyncState() {
      if (!payload.data_api_base_url) return;
      const [sourcesResponse, schedulesResponse] = await Promise.all([
        fetch(dataApiUrl("/api/instrument-sources"), instrumentRequestOptions()),
        fetch(dataApiUrl("/api/instrument-sync/schedules"), instrumentRequestOptions()),
      ]);
      if (!sourcesResponse.ok || !schedulesResponse.ok) {
        throw new Error("Unable to load instrument sources");
      }
      const sourcesPayload = await sourcesResponse.json();
      const schedulesPayload = await schedulesResponse.json();
      instrumentState.syncSources = Array.isArray(sourcesPayload.sources) ? sourcesPayload.sources : [];
      instrumentState.syncSchedules = Array.isArray(schedulesPayload.schedules) ? schedulesPayload.schedules : [];
      renderInstrumentSyncDialog();
    }

    function renderInstrumentSyncDialog() {
      const sourceRows = document.getElementById("instrumentSourceRows");
      sourceRows.innerHTML = instrumentState.syncSources.length ? instrumentState.syncSources.map((source) => `
        <div class="sync-row">
          <div>
            <div class="sync-row-title">${escapeHtml(source.source_label || source.source_id)}</div>
            <div class="sync-row-meta">${escapeHtml(source.provider_type || "")} · ${escapeHtml(JSON.stringify(source.provider_config || {}))}</div>
          </div>
          <button type="button" data-sync-source-id="${escapeHtml(source.source_id)}">Sync Now</button>
        </div>
      `).join("") : `<div class="empty">No sync sources</div>`;
      for (const button of sourceRows.querySelectorAll("[data-sync-source-id]")) {
        button.addEventListener("click", () => runInstrumentSourceSync(button.dataset.syncSourceId || ""));
      }
      const sourceSelect = document.getElementById("instrumentSyncScheduleSource");
      sourceSelect.innerHTML = instrumentState.syncSources.map((source) => (
        `<option value="${escapeHtml(source.source_id)}">${escapeHtml(source.source_label || source.source_id)}</option>`
      )).join("");
      renderInstrumentSyncSchedules();
      document.getElementById("instrumentSyncError").textContent = instrumentState.syncMessage || "";
    }

    function renderInstrumentSyncSchedules() {
      const rows = document.getElementById("instrumentSyncScheduleRows");
      rows.innerHTML = instrumentState.syncSchedules.length ? instrumentState.syncSchedules.map((schedule) => `
        <div class="sync-row">
          <div>
            <div class="sync-row-title">${escapeHtml(schedule.name || schedule.schedule_id)}</div>
            <div class="sync-row-meta">${escapeHtml(schedule.config?.source_id || "")} · ${escapeHtml(schedule.status || "")}</div>
          </div>
          <div class="row-actions">
            <button type="button" data-sync-schedule-action="run" data-sync-schedule-id="${escapeHtml(schedule.schedule_id)}">Run</button>
            <button type="button" data-sync-schedule-action="${schedule.enabled ? "disable" : "enable"}" data-sync-schedule-id="${escapeHtml(schedule.schedule_id)}">${schedule.enabled ? "Disable" : "Enable"}</button>
            <button type="button" data-sync-schedule-action="delete" data-sync-schedule-id="${escapeHtml(schedule.schedule_id)}">×</button>
          </div>
        </div>
      `).join("") : `<div class="empty">No sync schedules</div>`;
      for (const button of rows.querySelectorAll("[data-sync-schedule-action]")) {
        button.addEventListener("click", () => handleInstrumentSyncScheduleAction(button.dataset.syncScheduleAction || "", button.dataset.syncScheduleId || ""));
      }
    }

    async function runInstrumentSourceSync(sourceId) {
      if (!sourceId) return;
      const payload = { source_id: sourceId };
      const response = await fetch(dataApiUrl("/api/instrument-sync/run"), instrumentMutationOptions("POST", payload));
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      instrumentState.syncMessage = `Synced ${result.source_id}: ${result.created} created, ${result.updated} updated`;
      await loadInstrumentManager();
      await loadInstrumentSyncState();
    }

    async function createInstrumentSyncSchedule(event) {
      event.preventDefault();
      const sourceId = document.getElementById("instrumentSyncScheduleSource").value;
      const every = Number(document.getElementById("instrumentSyncEvery").value) || 1;
      const unit = document.getElementById("instrumentSyncUnit").value || "hours";
      const name = document.getElementById("instrumentSyncScheduleName").value.trim()
        || `${sourceId} instruments`;
      const payload = {
        name,
        enabled: document.getElementById("instrumentSyncEnabled").checked,
        source_id: sourceId,
        trigger: {
          type: "interval",
          every,
          unit,
          start_at: new Date().toISOString(),
          timezone: "Asia/Shanghai",
        },
      };
      const response = await fetch(dataApiUrl("/api/instrument-sync/schedules"), instrumentMutationOptions("POST", payload));
      if (!response.ok) throw new Error(await response.text());
      instrumentState.syncMessage = `Created schedule ${name}`;
      document.getElementById("instrumentSyncScheduleForm").reset();
      await loadInstrumentSyncState();
    }

    async function handleInstrumentSyncScheduleAction(action, scheduleId) {
      if (!action || !scheduleId) return;
      if (action === "delete" && !window.confirm("Delete this sync schedule?")) return;
      const path = action === "delete"
        ? `/api/instrument-sync/schedules/${encodeURIComponent(scheduleId)}`
        : `/api/instrument-sync/schedules/${encodeURIComponent(scheduleId)}/${action === "run" ? "run-now" : action}`;
      const method = action === "delete" ? "DELETE" : "POST";
      const response = await fetch(dataApiUrl(path), instrumentMutationOptions(method, {}));
      if (!response.ok) throw new Error(await response.text());
      instrumentState.syncMessage = action === "run" ? "Schedule run completed" : "Schedule updated";
      if (action === "run") await loadInstrumentManager();
      await loadInstrumentSyncState();
    }
```

- [ ] **Step 6: Wire modal events**

Add event listeners near existing dialog listeners:

```javascript
    document.getElementById("openInstrumentSyncDialogButton").addEventListener("click", async () => {
      const dialog = document.getElementById("instrumentSyncDialog");
      try {
        await loadInstrumentSyncState();
      } catch (error) {
        instrumentState.syncMessage = error.message;
        renderInstrumentSyncDialog();
      }
      if (dialog.showModal) dialog.showModal();
    });
    document.getElementById("closeInstrumentSyncDialogButton").addEventListener("click", () => {
      document.getElementById("instrumentSyncDialog").close();
    });
    document.getElementById("instrumentSyncScheduleForm").addEventListener("submit", createInstrumentSyncSchedule);
```

- [ ] **Step 7: Run workbench HTML tests**

Run:

```bash
uv run pytest tests/charts/test_workbench_server.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backtest/charts/workbench_server.py tests/charts/test_workbench_server.py
git commit -m "feat: add instrument source sync workbench"
```

---

### Task 6: Full Verification And Local Browser Check

**Files:**
- No required source edits unless verification finds a bug.

- [ ] **Step 1: Run focused backend and workbench tests**

Run:

```bash
uv run pytest tests/data/test_instrument_store.py tests/data_source/test_instrument_sync.py tests/data_source/test_api.py tests/data_source/test_server.py tests/charts/test_workbench_server.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the broader relevant suite**

Run:

```bash
uv run pytest tests/data_source tests/charts/test_workbench_server.py -q
```

Expected: PASS.

- [ ] **Step 3: Restart local datasource**

Stop the existing listener on port 8878, then run:

```bash
uv run backtest data-source serve \
  --bitget-bars-root data/crypto/bitget/bars \
  --bitget-metadata /tmp/backtest-instrument-ui/metadata.sqlite \
  --a-share-bars-root data/bars \
  --a-share-metadata /tmp/backtest-instrument-ui/metadata.sqlite \
  --schedule-db /tmp/backtest-instrument-ui/schedules.sqlite \
  --host 127.0.0.1 \
  --port 8878 \
  --scheduler
```

Expected: service starts and prints the local URL with two sources.

- [ ] **Step 4: Restart local workbench**

Stop the existing listener on port 8877, then run:

```bash
uv run backtest chart serve-workbench \
  --results-root runs \
  --a-share-bars-root data/bars \
  --bitget-bars-root data/crypto/bitget/bars \
  --host 127.0.0.1 \
  --port 8877 \
  --data-api-base-url http://127.0.0.1:8878
```

Expected: workbench starts at `http://127.0.0.1:8877`.

- [ ] **Step 5: Verify HTTP manually**

Run:

```bash
curl -sS http://127.0.0.1:8878/api/instrument-sources
curl -sS -X POST http://127.0.0.1:8878/api/instrument-sync/run \
  -H 'Content-Type: application/json' \
  -d '{"source_id":"bitget"}'
curl -sS 'http://127.0.0.1:8878/api/instruments?source_id=bitget&limit=3'
curl -sS http://127.0.0.1:8878/api/instrument-tags
```

Expected:

- `instrument-sources` includes `bitget` and `a_share`.
- sync result returns `status=success`.
- Bitget instruments are present with `source_id=bitget`.
- `Bitget` tag exists and has members.

- [ ] **Step 6: Verify in the in-app browser**

Use the Browser plugin to open:

```text
http://127.0.0.1:8877/instruments
```

Check:

- `Sources` button is visible.
- Opening the modal lists Bitget and A-share.
- `Sync Now` on Bitget runs and refreshes counts.
- Instrument pagination still shows correct totals.
- Selecting a Bitget instrument and clicking `Open K-line` navigates to `/kline`
  with the selected symbol and source.

- [ ] **Step 7: Commit any verification fixes**

If verification required fixes:

```bash
git add <fixed files>
git commit -m "fix: verify instrument source sync flow"
```

If no fixes were needed, do not create an empty commit.

---

## Self-Review Checklist

- Spec coverage:
  - Source discovery: Task 2 and Task 3.
  - Provider abstraction: Task 2.
  - CCXT exchange compatibility: Task 2.
  - Manual HTTP sync: Task 3.
  - Scheduled sync: Task 4.
  - Source default tags: Task 2.
  - Global `All` inventory preservation: Task 3 and Task 5.
  - Workbench entry: Task 5.
  - Browser verification: Task 6.
- Placeholder scan:
  - No unfinished-marker steps or vague deferred work.
- Type consistency:
  - `InstrumentSourceDefinition`, `InstrumentCatalogItem`,
    `InstrumentSyncService`, `InstrumentSyncScheduleService`, and route names
    are consistent across tasks.
