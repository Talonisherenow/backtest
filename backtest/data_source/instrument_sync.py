from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Event, Thread
from typing import Any, Callable, Protocol
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import BaseModel, Field, field_validator

from backtest.data.instruments import InstrumentStore
from backtest.data.sqlite_util import open_sqlite_connection
from backtest.data_source.config import DataSourceServerConfig, DataSourceSpec
from backtest.data_source.schedules import (
    DEFAULT_TIMEZONE,
    RepeatConfig,
    TriggerConfig,
    compute_next_run_at,
)


LOGGER = logging.getLogger(__name__)


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
        provider_type = "akshare"
        provider_config = {}
    elif catalog_source == "universe_csv":
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
        self._disable_currency_prefetch(self.exchange)

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
        config: dict[str, Any] = {"enableRateLimit": True}
        proxies = CCXTInstrumentCatalogProvider._proxy_config_from_env()
        if proxies:
            config["proxies"] = proxies
        return exchange_cls(config)

    @staticmethod
    def _proxy_config_from_env() -> dict[str, str]:
        all_proxy = os.environ.get("CCXT_PROXY") or os.environ.get("ALL_PROXY") or os.environ.get("all_proxy")
        http_proxy = (
            os.environ.get("CCXT_HTTP_PROXY")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("http_proxy")
            or all_proxy
        )
        https_proxy = (
            os.environ.get("CCXT_HTTPS_PROXY")
            or os.environ.get("HTTPS_PROXY")
            or os.environ.get("https_proxy")
            or all_proxy
        )
        proxies: dict[str, str] = {}
        if http_proxy:
            proxies["http"] = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy
        return proxies

    @staticmethod
    def _disable_currency_prefetch(exchange: Any) -> None:
        capabilities = getattr(exchange, "has", None)
        if isinstance(capabilities, dict) and capabilities.get("fetchCurrencies") is True:
            capabilities["fetchCurrencies"] = False

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
        if not self.universe_path.exists():
            raise ValueError(f"Universe CSV does not exist: {self.universe_path}")
        frame = pd.read_csv(self.universe_path)
        if "symbol" not in frame.columns:
            raise ValueError(f"Universe CSV must include symbol column: {self.universe_path}")
        return _instruments_from_universe_frame(
            source_id=self.source_id,
            asset_class=self.asset_class,
            frame=frame,
        )


class AkShareInstrumentCatalogProvider:
    def __init__(
        self,
        *,
        source_id: str,
        asset_class: str,
        frame_factory: Callable[[], pd.DataFrame] | None = None,
    ) -> None:
        self.source_id = source_id
        self.asset_class = asset_class
        self.frame_factory = frame_factory or self._default_frame_factory

    def list_instruments(self) -> list[InstrumentCatalogItem]:
        frame = self.frame_factory()
        if "symbol" not in frame.columns:
            raise ValueError("AkShare universe frame must include symbol column")
        return _instruments_from_universe_frame(
            source_id=self.source_id,
            asset_class=self.asset_class,
            frame=frame,
        )

    @staticmethod
    def _default_frame_factory() -> pd.DataFrame:
        from backtest.data.universe import AkShareUniverseProvider

        return AkShareUniverseProvider().fetch_a_share_universe()


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
    if definition.provider_type == "akshare":
        return AkShareInstrumentCatalogProvider(
            source_id=definition.source_id,
            asset_class=definition.asset_class,
        )
    if definition.provider_type == "universe_csv":
        return UniverseCsvInstrumentCatalogProvider(
            source_id=definition.source_id,
            asset_class=definition.asset_class,
            universe_path=str(definition.provider_config["path"]),
        )
    raise ValueError(f"Unsupported provider type: {definition.provider_type}")


def _instruments_from_universe_frame(
    *,
    source_id: str,
    asset_class: str,
    frame: pd.DataFrame,
) -> list[InstrumentCatalogItem]:
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
                instrument_id=_scoped_instrument_id(source_id, symbol),
                symbol=symbol,
                name=_clean_optional_text(row.get("name")),
                market=source_id,
                exchange=exchange,
                asset_class=asset_class,
                quote_currency=None,
                source_id=source_id,
                metadata=_row_metadata(row),
            )
        )
    return items


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
        for item in items:
            result = store.upsert_instrument(item.to_instrument_payload(), touch=True)
            counts[result.action] += 1
            store.add_tag_members(definition.default_tag_id, [result.record.instrument_id])

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


class InstrumentSyncScheduleConfig(BaseModel):
    name: str
    enabled: bool = False
    source_id: str
    trigger: TriggerConfig
    repeat: RepeatConfig = Field(default_factory=RepeatConfig)

    @field_validator("name", "source_id")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be empty")
        return normalized


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
            "result": dict(self.result_json) if self.result_json is not None else None,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
        }


class InstrumentSyncScheduleStore:
    def __init__(
        self,
        path: str | Path,
        *,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.now = now
        self._lock = threading.Lock()
        self._init_schema()

    def connect(self):
        return open_sqlite_connection(self.path)

    def create(
        self,
        config: InstrumentSyncScheduleConfig,
        *,
        next_run_at: datetime | None,
    ) -> InstrumentSyncScheduleSnapshot:
        now = self.now()
        with self._lock:
            schedule_id = _unique_id(
                self,
                "instrument_sync_schedules",
                "schedule_id",
                now,
                config.name,
            )
            status = "enabled" if config.enabled else "disabled"
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
                        status,
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
            rows = conn.execute(
                "SELECT * FROM instrument_sync_schedules ORDER BY created_at, schedule_id"
            ).fetchall()
        return [self._snapshot(row) for row in rows]

    def due(self, now: datetime) -> list[InstrumentSyncScheduleSnapshot]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM instrument_sync_schedules
                WHERE enabled = 1 AND next_run_at IS NOT NULL
                ORDER BY next_run_at, schedule_id
                """
            ).fetchall()
        snapshots = [self._snapshot(row) for row in rows]
        return [
            snapshot
            for snapshot in snapshots
            if snapshot.next_run_at is not None
            and _datetime_lte(snapshot.next_run_at, now)
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
        status = "enabled" if config.enabled else "disabled"
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
                    status,
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
            conn.execute(
                "DELETE FROM instrument_sync_schedule_runs WHERE schedule_id = ?",
                (schedule_id,),
            )

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
                self,
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
                        json.dumps(result, ensure_ascii=False) if result is not None else None,
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


class InstrumentSyncScheduleService:
    def __init__(
        self,
        *,
        store: InstrumentSyncScheduleStore,
        config: DataSourceServerConfig,
        sync_source: Callable[[str], dict[str, Any]],
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.store = store
        self.config = config
        self.sync_source = sync_source
        self.now = now
        self._run_lock = threading.Lock()
        self._running_schedule_ids: set[str] = set()

    def list(self) -> dict[str, list[dict[str, Any]]]:
        return {"schedules": [snapshot.to_dict() for snapshot in self.store.list()]}

    def get(self, schedule_id: str) -> InstrumentSyncScheduleSnapshot:
        return self.store.get(schedule_id)

    def create(self, payload: dict[str, Any]) -> InstrumentSyncScheduleSnapshot:
        config = InstrumentSyncScheduleConfig.model_validate(payload)
        self.config.source(config.source_id)
        next_run_at = (
            compute_next_run_at(config, now=self.now(), run_count=0) if config.enabled else None
        )
        config, next_run_at = _disable_enabled_without_next_run(config, next_run_at)
        return self.store.create(config, next_run_at=next_run_at)

    def update(
        self,
        schedule_id: str,
        payload: dict[str, Any],
    ) -> InstrumentSyncScheduleSnapshot:
        current = self.store.get(schedule_id)
        merged = current.config.model_dump(mode="json")
        _deep_update(merged, payload)
        config = InstrumentSyncScheduleConfig.model_validate(merged)
        self.config.source(config.source_id)
        next_run_at = (
            compute_next_run_at(config, now=self.now(), run_count=current.run_count)
            if config.enabled
            else None
        )
        config, next_run_at = _disable_enabled_without_next_run(config, next_run_at)
        return self.store.update_config(schedule_id, config, next_run_at=next_run_at)

    def delete(self, schedule_id: str) -> dict[str, str]:
        with self._run_lock:
            if schedule_id in self._running_schedule_ids:
                raise ValueError(f"Instrument sync schedule already running: {schedule_id}")
        self.store.delete(schedule_id)
        return {"deleted": schedule_id}

    def enable(self, schedule_id: str) -> InstrumentSyncScheduleSnapshot:
        current = self.store.get(schedule_id)
        config = current.config.model_copy(update={"enabled": True})
        next_run_at = compute_next_run_at(config, now=self.now(), run_count=current.run_count)
        config, next_run_at = _disable_enabled_without_next_run(config, next_run_at)
        return self.store.update_config(schedule_id, config, next_run_at=next_run_at)

    def disable(self, schedule_id: str) -> InstrumentSyncScheduleSnapshot:
        current = self.store.get(schedule_id)
        config = current.config.model_copy(update={"enabled": False})
        return self.store.update_config(schedule_id, config, next_run_at=None)

    def run_now(self, schedule_id: str) -> dict[str, Any]:
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

    def _run(
        self,
        snapshot: InstrumentSyncScheduleSnapshot,
        *,
        due_at: datetime,
    ) -> dict[str, Any]:
        self._enter_run(snapshot.schedule_id)
        try:
            triggered_at = self.now()
            self.store.update_state(
                snapshot.schedule_id,
                enabled=snapshot.enabled,
                status="running",
                run_count=snapshot.run_count,
                next_run_at=snapshot.next_run_at,
                last_run_at=snapshot.last_run_at,
                last_error=snapshot.last_error,
            )
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
            status = "enabled" if enabled else ("completed" if snapshot.enabled else "disabled")
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
                status=status,
                run_count=next_count,
                next_run_at=next_run_at,
                last_run_at=triggered_at,
                last_error=None,
            )
            return result
        except Exception as exc:
            triggered_at = self.now()
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
            enabled = snapshot.enabled and next_run_at is not None
            self.store.update_state(
                snapshot.schedule_id,
                enabled=enabled,
                status="error",
                run_count=snapshot.run_count,
                next_run_at=next_run_at,
                last_run_at=triggered_at,
                last_error=str(exc),
            )
            raise
        finally:
            self._exit_run(snapshot.schedule_id)

    def _enter_run(self, schedule_id: str) -> None:
        with self._run_lock:
            if schedule_id in self._running_schedule_ids:
                raise ValueError(f"Instrument sync schedule already running: {schedule_id}")
            self._running_schedule_ids.add(schedule_id)

    def _exit_run(self, schedule_id: str) -> None:
        with self._run_lock:
            self._running_schedule_ids.discard(schedule_id)

class InstrumentSyncScheduler:
    def __init__(self, *, service: InstrumentSyncScheduleService, poll_seconds: float) -> None:
        self.service = service
        self.poll_seconds = poll_seconds
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
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
            except Exception:
                LOGGER.exception("Instrument sync scheduler tick failed")
            finally:
                self._stop.wait(self.poll_seconds)


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


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _unique_id(
    store: InstrumentSyncScheduleStore,
    table: str,
    column: str,
    when: datetime,
    name: str,
) -> str:
    base = f"{when:%Y%m%d%H%M%S}-{_slug(name)}"
    with store.connect() as conn:
        rows = conn.execute(f"SELECT {column} AS value FROM {table}").fetchall()
    existing = {row["value"] for row in rows}
    candidate = base
    counter = 2
    while candidate in existing:
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "schedule"


def _deep_update(target: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value


def _disable_enabled_without_next_run(
    config: InstrumentSyncScheduleConfig,
    next_run_at: datetime | None,
) -> tuple[InstrumentSyncScheduleConfig, datetime | None]:
    if config.enabled and next_run_at is None:
        return config.model_copy(update={"enabled": False}), None
    return config, next_run_at


def _datetime_lte(left: datetime, right: datetime) -> bool:
    if left.tzinfo is None and right.tzinfo is None:
        return left <= right
    zone = ZoneInfo(DEFAULT_TIMEZONE)
    return _aware_datetime(left, zone) <= _aware_datetime(right, zone)


def _aware_datetime(value: datetime, zone: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=zone)
    return value.astimezone(zone)
