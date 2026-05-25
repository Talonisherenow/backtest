from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol

import pandas as pd

from backtest.data.instruments import InstrumentStore
from backtest.data_source.config import DataSourceServerConfig, DataSourceSpec


@dataclass(frozen=True)
class InstrumentSourceDefinition:
    source_id: str
    source_label: str
    asset_class: str
    provider_type: str
    provider_config: dict[str, Any]
    default_tag_id: str
    default_tag_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_label": self.source_label,
            "asset_class": self.asset_class,
            "provider_type": self.provider_type,
            "provider_config": dict(self.provider_config),
            "default_tag_id": self.default_tag_id,
            "default_tag_name": self.default_tag_name,
        }


@dataclass(frozen=True)
class InstrumentCatalogItem:
    instrument_id: str
    symbol: str
    name: str | None
    market: str
    exchange: str | None
    asset_class: str
    quote_currency: str | None
    source_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_instrument_payload(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "name": self.name,
            "market": self.market,
            "exchange": self.exchange,
            "asset_class": self.asset_class,
            "quote_currency": self.quote_currency,
            "source_id": self.source_id,
            "metadata": dict(self.metadata),
        }


class InstrumentCatalogProvider(Protocol):
    def list_instruments(self) -> list[InstrumentCatalogItem]:
        ...


def source_definition_from_spec(spec: DataSourceSpec) -> InstrumentSourceDefinition:
    catalog_source = spec.catalog_source.strip()
    if catalog_source.startswith("ccxt:"):
        exchange = catalog_source.removeprefix("ccxt:").strip()
        if not exchange:
            raise ValueError(f"Unsupported catalog source: {spec.catalog_source}")
        provider_type = "ccxt"
        provider_config: dict[str, Any] = {"exchange": exchange}
    elif catalog_source == "akshare":
        if spec.universe_path is None:
            raise ValueError(f"Universe path is required for source: {spec.source_id}")
        provider_type = "universe_csv"
        provider_config = {"path": str(spec.universe_path)}
    else:
        raise ValueError(f"Unsupported catalog source: {spec.catalog_source}")

    return InstrumentSourceDefinition(
        source_id=spec.source_id,
        source_label=spec.source_label,
        asset_class=spec.asset_class,
        provider_type=provider_type,
        provider_config=provider_config,
        default_tag_id=spec.source_id,
        default_tag_name=spec.source_label,
    )


def _scoped_instrument_id(source_id: str, symbol: str) -> str:
    return f"{source_id}:{symbol}".upper()


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
        self.exchange = exchange if exchange is not None else self._build_exchange(exchange_id)

    def list_instruments(self) -> list[InstrumentCatalogItem]:
        markets = self.exchange.load_markets()
        items: list[InstrumentCatalogItem] = []
        for key in sorted(markets):
            market = markets[key]
            if market.get("active") is False:
                continue
            symbol = str(market.get("symbol") or key).upper()
            quote = _clean_optional_text(market.get("quote"), upper=True)
            items.append(
                InstrumentCatalogItem(
                    instrument_id=_scoped_instrument_id(self.source_id, symbol),
                    symbol=symbol,
                    name=None,
                    market=self._market_type(market),
                    exchange=str(getattr(self.exchange, "id", self.exchange_id)),
                    asset_class=self.asset_class,
                    quote_currency=quote,
                    source_id=self.source_id,
                    metadata={
                        "base": _clean_optional_text(market.get("base"), upper=True),
                        "quote": quote,
                        "ccxt_id": market.get("id"),
                        "spot": bool(market.get("spot")),
                        "swap": bool(market.get("swap")),
                        "future": bool(market.get("future")),
                    },
                )
            )
        return items

    @staticmethod
    def _build_exchange(exchange_id: str) -> Any:
        try:
            import ccxt
        except ImportError as exc:
            raise ValueError("ccxt is required for ccxt catalog sources") from exc
        exchange_cls = getattr(ccxt, exchange_id, None)
        if exchange_cls is None:
            raise ValueError(f"Unknown ccxt exchange: {exchange_id}")
        return exchange_cls()

    @staticmethod
    def _market_type(market: dict[str, Any]) -> str:
        if market.get("spot"):
            return "crypto_spot"
        if market.get("swap"):
            return "crypto_swap"
        if market.get("future"):
            return "crypto_future"
        return "crypto"


class UniverseCsvInstrumentCatalogProvider:
    def __init__(
        self,
        *,
        source_id: str,
        asset_class: str,
        universe_path: str | Path,
    ) -> None:
        self.source_id = source_id
        self.asset_class = asset_class
        self.universe_path = Path(universe_path)

    def list_instruments(self) -> list[InstrumentCatalogItem]:
        frame = pd.read_csv(self.universe_path)
        if "symbol" not in frame.columns:
            raise ValueError(f"Universe CSV must include symbol column: {self.universe_path}")

        items: list[InstrumentCatalogItem] = []
        for row in frame.to_dict(orient="records"):
            raw_symbol = row.get("symbol")
            if pd.isna(raw_symbol):
                continue
            symbol = str(raw_symbol).strip().upper()
            if not symbol:
                continue
            exchange = _clean_optional_text(row.get("exchange"), upper=True)
            items.append(
                InstrumentCatalogItem(
                    instrument_id=_scoped_instrument_id(self.source_id, symbol),
                    symbol=symbol,
                    name=_clean_optional_text(row.get("name")),
                    market=self.source_id,
                    exchange=exchange,
                    asset_class=self.asset_class,
                    quote_currency=None,
                    source_id=self.source_id,
                    metadata=_row_metadata(row),
                )
            )
        return items


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
        return UniverseCsvInstrumentCatalogProvider(
            source_id=definition.source_id,
            asset_class=definition.asset_class,
            universe_path=str(definition.provider_config["path"]),
        )
    raise ValueError(f"Unsupported provider type: {definition.provider_type}")


class InstrumentSyncService:
    def __init__(
        self,
        *,
        config: DataSourceServerConfig,
        store_factory: Callable[[], InstrumentStore],
        provider_factory: Callable[
            [InstrumentSourceDefinition],
            InstrumentCatalogProvider,
        ] = build_instrument_catalog_provider,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.config = config
        self.store_factory = store_factory
        self.provider_factory = provider_factory
        self.now = now

    def sources(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "sources": [
                source_definition_from_spec(spec).to_dict()
                for spec in self.config.sources
            ]
        }

    def sync_source(self, source_id: str) -> dict[str, Any]:
        spec = self.config.source(source_id)
        definition = source_definition_from_spec(spec)
        provider = self.provider_factory(definition)
        items = provider.list_instruments()
        store = self.store_factory()
        store.ensure_tag(
            {
                "tag_id": definition.default_tag_id,
                "name": definition.default_tag_name,
            }
        )

        counts = {"created": 0, "updated": 0, "unchanged": 0, "failed": 0}
        successful_ids: list[str] = []
        for item in items:
            try:
                result = store.upsert_instrument(item.to_instrument_payload())
            except Exception:
                counts["failed"] += 1
                continue
            counts[result.action] += 1
            successful_ids.append(result.record.instrument_id)

        if successful_ids:
            store.add_tag_members(definition.default_tag_id, successful_ids)

        return {
            "source_id": definition.source_id,
            "status": "partial" if counts["failed"] else "success",
            "created": counts["created"],
            "updated": counts["updated"],
            "unchanged": counts["unchanged"],
            "failed": counts["failed"],
            "total": len(items),
            "tag_id": definition.default_tag_id,
            "synced_at": self.now().isoformat(),
        }


def _clean_optional_text(value: Any, *, upper: bool = False) -> str | None:
    if value is None or pd.isna(value):
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    return cleaned.upper() if upper else cleaned


def _row_metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key, value in row.items():
        if key in {"symbol", "name", "exchange"} or pd.isna(value):
            continue
        metadata[key] = value
    return metadata
