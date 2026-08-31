from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

from backtest.core.enums import Frequency

from backtest.charts.kline_service import KlineCacheService, KlineSource
from backtest.data.catalog import DataCatalog
from backtest.data.instruments import InstrumentStore
from backtest.data.jobs import DataSyncJobConfig
from backtest.data.metadata import MetadataStore
from backtest.data.tasks import CrawlTaskManager
from backtest.data_source.config import DataSourceServerConfig, DataSourceSpec
from backtest.data_source.instrument_sync import (
    InstrumentSyncScheduleService,
    InstrumentSyncScheduleStore,
    InstrumentSyncService,
)
from backtest.data_source.jobs import DataSourceJobRegistry
from backtest.data_source.schedules import DataSourceScheduleService
from backtest.data_source.task_summary_cache import (
    CachedTaskSummary,
    CrawlTaskSummaryCache,
    CrawlTaskSummaryRefresher,
    utc_now,
)

LOGGER = logging.getLogger(__name__)


class DataSourceApi:
    def __init__(
        self,
        config: DataSourceServerConfig,
        job_registry: DataSourceJobRegistry,
        *,
        task_summary_cache: CrawlTaskSummaryCache | None = None,
    ) -> None:
        self.config = config
        self.job_registry = job_registry
        self.schedule_service: DataSourceScheduleService | None = None
        self.instrument_sync_service: InstrumentSyncService | None = None
        self.instrument_sync_schedule_service: InstrumentSyncScheduleService | None = None
        self.task_summary_cache = task_summary_cache or CrawlTaskSummaryCache()
        self.task_summary_refresher = CrawlTaskSummaryRefresher(
            refresh_all=self.refresh_task_summaries,
            poll_seconds=config.task_summary_refresh_seconds,
        )
        self.kline_service = KlineCacheService(
            sources=[
                KlineSource(
                    source_id=spec.source_id,
                    source_label=spec.source_label,
                    bars_root=spec.bars_root,
                    adjust=spec.adjust,
                    universe_path=spec.universe_path,
                )
                for spec in config.sources
            ]
        )

    def health(self) -> dict[str, str]:
        return {"status": "ok", "service": "backtest-data-source"}

    def data_sources(self) -> dict[str, list[dict[str, object]]]:
        return {"sources": [spec.public_dict() for spec in self.config.sources]}

    def instrument_sources(self) -> dict[str, list[dict[str, object]]]:
        return self._instrument_sync().sources()

    def run_instrument_sync(self, payload: dict[str, Any]) -> dict[str, object]:
        source_id = payload.get("source_id")
        if not source_id:
            raise ValueError("source_id is required")
        return self._instrument_sync().sync_source(str(source_id))

    def kline_manifest(self, *, include_symbols: bool = True) -> dict[str, Any]:
        return self.kline_service.manifest(
            default_window_size=self.config.default_window_size,
            include_symbols=include_symbols,
        )

    def kline_symbols(
        self,
        *,
        source_id: str | None = None,
        q: str | None = None,
        board: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        return self.kline_service.symbols(
            source_id=source_id,
            q=q,
            board=board,
            limit=limit,
            offset=offset,
        )

    def kline_bars(
        self,
        *,
        source_id: str | None = None,
        symbol: str,
        frequency: str,
        adjust: str | None = None,
        limit: int = 300,
        offset: int | None = None,
        start: str | None = None,
        anchor: str | None = None,
    ) -> dict[str, Any]:
        return self.kline_service.bars(
            source_id=source_id,
            symbol=symbol,
            frequency=frequency,
            adjust=adjust,
            limit=limit,
            offset=offset,
            start=start,
            anchor=anchor,
        )

    def task_summary(self, source_id: str, *, fresh: bool = False) -> dict[str, Any]:
        self.config.source(source_id)
        if not fresh:
            cached = self.task_summary_cache.get(source_id)
            if cached is not None:
                return cached.to_response(from_cache=True)
        return self._refresh_task_summary(source_id).to_response(from_cache=False)

    def refresh_task_summaries(self) -> None:
        for spec in self.config.sources:
            try:
                self._refresh_task_summary(spec.source_id)
            except Exception as exc:
                LOGGER.exception("Failed to refresh task summary for %s", spec.source_id)
                existing = self.task_summary_cache.get(spec.source_id)
                if existing is None:
                    continue
                self.task_summary_cache.put(
                    spec.source_id,
                    CachedTaskSummary(
                        payload=existing.payload,
                        cached_at=existing.cached_at,
                        error=str(exc),
                    ),
                )

    def _refresh_task_summary(self, source_id: str) -> CachedTaskSummary:
        payload = self._compute_task_summary(source_id)
        entry = CachedTaskSummary(payload=payload, cached_at=utc_now(), error=None)
        self.task_summary_cache.put(source_id, entry)
        return entry

    def _compute_task_summary(self, source_id: str) -> dict[str, Any]:
        spec = self.config.source(source_id)
        summary = self._tasks(spec).task_summary()
        return {
            "source_id": source_id,
            "total": summary.total,
            "status_counts": summary.status_counts,
            "frequency_counts": summary.frequency_counts,
            "latest_updated_at": summary.latest_updated_at.isoformat()
            if summary.latest_updated_at
            else None,
        }

    def tasks(
        self,
        source_id: str,
        *,
        page: int = 1,
        page_size: int = 50,
        symbol: str | None = None,
        frequencies: list[str] | None = None,
        statuses: list[str] | None = None,
    ) -> dict[str, Any]:
        spec = self.config.source(source_id)
        normalized_frequencies = [Frequency(frequency) for frequency in frequencies or []]
        normalized_statuses = [status.strip() for status in statuses or [] if status.strip()]
        task_page = self._tasks(spec).list_tasks_page(
            page=page,
            page_size=page_size,
            symbol=symbol,
            frequencies=normalized_frequencies,
            statuses=normalized_statuses,
        )
        return {
            "source_id": source_id,
            "tasks": [self._jsonify(record) for record in task_page.tasks],
            "page": task_page.page,
            "page_size": task_page.page_size,
            "total": task_page.total,
            "total_pages": task_page.total_pages,
            "filters": {
                "symbol": symbol or "",
                "frequencies": [frequency.value for frequency in normalized_frequencies],
                "statuses": normalized_statuses,
            },
        }

    def inventory(self, source_id: str) -> dict[str, list[dict[str, Any]]]:
        spec = self.config.source(source_id)
        return {
            "records": [
                self._jsonify(record)
                for record in DataCatalog(self._metadata(spec)).inventory()
            ]
        }

    def instruments(
        self,
        *,
        source_id: str | None = None,
        q: str | None = None,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        effective_source_id = self._validate_source_id(source_id)
        return self._jsonify(
            self._instrument_store(effective_source_id).list_instruments(
                source_id=effective_source_id,
                q=q,
                tag=tag,
                limit=limit,
                offset=offset,
            )
        )

    def create_instrument(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_id = self._payload_source_id(payload)
        self._validate_source_id(source_id)
        return self._jsonify(self._instrument_store(source_id).create_instrument(payload))

    def instrument(
        self,
        instrument_id: str,
        *,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        effective_source_id = self._validate_source_id(source_id)
        record = self._instrument_store(effective_source_id).get_instrument(instrument_id)
        self._ensure_instrument_source(record, effective_source_id)
        return self._jsonify(record)

    def update_instrument(
        self,
        instrument_id: str,
        payload: dict[str, Any],
        *,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        effective_source_id = self._validate_source_id(source_id)
        self._validate_source_id(self._payload_source_id(payload))
        store = self._instrument_store(effective_source_id)
        self._ensure_instrument_source(store.get_instrument(instrument_id), effective_source_id)
        return self._jsonify(store.update_instrument(instrument_id, payload))

    def delete_instrument(
        self,
        instrument_id: str,
        *,
        source_id: str | None = None,
    ) -> dict[str, str]:
        effective_source_id = self._validate_source_id(source_id)
        store = self._instrument_store(effective_source_id)
        self._ensure_instrument_source(store.get_instrument(instrument_id), effective_source_id)
        store.delete_instrument(instrument_id)
        return {"deleted": instrument_id.strip().upper()}

    def instrument_tags(self, *, source_id: str | None = None) -> dict[str, Any]:
        effective_source_id = self._validate_source_id(source_id)
        store = self._instrument_store(effective_source_id)
        tags = store.list_tags()
        if effective_source_id is None:
            return {"tags": self._jsonify(tags)}
        filtered_tags = []
        for tag in tags:
            source_member_count = 0
            for member in store.tag_members(tag.tag_id).members:
                record = store.get_instrument(member.instrument_id)
                if record.source_id == effective_source_id:
                    source_member_count += 1
            if source_member_count or tag.tag_id == effective_source_id:
                filtered_tags.append(tag.model_copy(update={"member_count": source_member_count}))
        return {"tags": self._jsonify(filtered_tags)}

    def instrument_tag_members(
        self,
        tag_id: str,
        *,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        effective_source_id = self._validate_source_id(source_id)
        store = self._instrument_store(effective_source_id)
        members = self._jsonify(store.tag_members(tag_id))
        if effective_source_id is None:
            return members
        filtered_members = []
        for member in members["members"]:
            record = store.get_instrument(member["instrument_id"])
            if record.source_id == effective_source_id:
                filtered_members.append(member)
        members["members"] = filtered_members
        members["tag"]["member_count"] = len(filtered_members)
        return members

    def create_instrument_tag(self, payload: dict[str, Any]) -> dict[str, Any]:
        source_id = self._payload_source_id(payload)
        self._validate_source_id(source_id)
        return self._jsonify(self._instrument_store(source_id).create_tag(payload))

    def update_instrument_tag(
        self,
        tag_id: str,
        payload: dict[str, Any],
        *,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        self._validate_source_id(source_id)
        return self._jsonify(self._instrument_store(source_id).update_tag(tag_id, payload))

    def delete_instrument_tag(
        self,
        tag_id: str,
        *,
        source_id: str | None = None,
    ) -> dict[str, str]:
        self._validate_source_id(source_id)
        self._instrument_store(source_id).delete_tag(tag_id)
        return {"deleted": tag_id.strip()}

    def replace_instrument_tag_members(
        self,
        tag_id: str,
        payload: dict[str, Any],
        *,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        effective_source_id = self._validate_source_id(
            source_id or self._payload_source_id(payload)
        )
        store = self._instrument_store(effective_source_id)
        instrument_ids = self._payload_instrument_ids(payload)
        self._ensure_instruments_source(
            store,
            instrument_ids,
            effective_source_id,
        )
        if effective_source_id is not None:
            preserved_ids = [
                member.instrument_id
                for member in store.tag_members(tag_id).members
                if store.get_instrument(member.instrument_id).source_id != effective_source_id
            ]
            instrument_ids = [*preserved_ids, *instrument_ids]
        return self._jsonify(
            store.replace_tag_members(
                tag_id,
                instrument_ids,
            )
        )

    def add_instrument_tag_members(
        self,
        tag_id: str,
        payload: dict[str, Any],
        *,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        effective_source_id = self._validate_source_id(
            source_id or self._payload_source_id(payload)
        )
        self._ensure_instruments_source(
            self._instrument_store(effective_source_id),
            self._payload_instrument_ids(payload),
            effective_source_id,
        )
        return self._jsonify(
            self._instrument_store(effective_source_id).add_tag_members(
                tag_id,
                self._payload_instrument_ids(payload),
            )
        )

    def remove_instrument_tag_member(
        self,
        tag_id: str,
        instrument_id: str,
        *,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        effective_source_id = self._validate_source_id(source_id)
        store = self._instrument_store(effective_source_id)
        self._ensure_instrument_source(store.get_instrument(instrument_id), effective_source_id)
        return self._jsonify(
            store.remove_tag_member(tag_id, instrument_id)
        )

    def retry_failed(self, source_id: str) -> dict[str, object]:
        spec = self.config.source(source_id)
        tasks = self._tasks(spec)
        records = tasks.failed_tasks()
        task_ids: list[int] = []
        for record in records:
            if record.task_id is not None:
                tasks.mark_retrying(record.task_id)
                task_ids.append(record.task_id)
        return {"queued": len(task_ids), "task_ids": task_ids}

    def submit_job(self, payload: dict[str, Any]) -> dict[str, object]:
        config = DataSyncJobConfig.model_validate(self._normalize_job_payload(payload))
        return self.job_registry.submit(config).to_dict()

    def jobs(self) -> dict[str, list[dict[str, object]]]:
        return {"jobs": [snapshot.to_dict() for snapshot in self.job_registry.list()]}

    def job(self, job_id: str) -> dict[str, object]:
        return self.job_registry.get(job_id).to_dict()

    def schedule_options(self) -> dict[str, Any]:
        return self._schedules().options()

    def schedules(self) -> dict[str, list[dict[str, Any]]]:
        return self._schedules().list()

    def schedule(self, schedule_id: str) -> dict[str, Any]:
        return self._schedules().get(schedule_id).to_dict()

    def create_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._schedules().create(payload).to_dict()

    def update_schedule(self, schedule_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._schedules().update(schedule_id, payload).to_dict()

    def delete_schedule(self, schedule_id: str) -> dict[str, str]:
        return self._schedules().delete(schedule_id)

    def enable_schedule(self, schedule_id: str) -> dict[str, Any]:
        return self._schedules().enable(schedule_id).to_dict()

    def disable_schedule(self, schedule_id: str) -> dict[str, Any]:
        return self._schedules().disable(schedule_id).to_dict()

    def run_schedule_now(self, schedule_id: str) -> dict[str, Any]:
        return self._schedules().run_now(schedule_id)

    def schedule_runs(
        self,
        schedule_id: str,
        *,
        limit: int | None = 50,
    ) -> dict[str, list[dict[str, Any]]]:
        return self._schedules().runs(schedule_id, limit=limit)

    def resolve_schedule_symbols(
        self,
        source_id: str,
        target: Any | None,
        fallback_symbols: list[str],
    ) -> list[str]:
        effective_source_id = self._validate_source_id(source_id)
        if target is None:
            if not fallback_symbols:
                raise ValueError("symbols or target is required")
            return list(fallback_symbols)
        mode = self._target_value(target, "mode")
        store = self._instrument_store(effective_source_id)
        if mode == "symbols":
            instrument_ids = self._target_value(target, "instrument_ids") or []
            symbols: list[str] = []
            for instrument_id in instrument_ids:
                record = store.get_instrument(str(instrument_id))
                self._ensure_instrument_source(record, effective_source_id)
                symbols.append(self._record_symbol(record))
            if not symbols:
                raise ValueError("instrument_ids are required for symbols target")
            return symbols
        if mode == "tag":
            tag_id = self._target_value(target, "tag_id")
            if not tag_id:
                raise ValueError("tag_id is required for tag target")
            members = store.tag_members(str(tag_id)).members
            symbols = []
            for member in members:
                record = store.get_instrument(member.instrument_id)
                if record.source_id == effective_source_id:
                    symbols.append(self._record_symbol(record))
            if not symbols:
                raise ValueError(f"Instrument list has no symbols for source: {effective_source_id}")
            return symbols
        raise ValueError(f"Unsupported schedule target mode: {mode}")

    def instrument_sync_schedules(self) -> dict[str, list[dict[str, Any]]]:
        return self._instrument_sync_schedules().list()

    def instrument_sync_schedule(self, schedule_id: str) -> dict[str, Any]:
        return self._instrument_sync_schedules().get(schedule_id).to_dict()

    def create_instrument_sync_schedule(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._instrument_sync_schedules().create(payload).to_dict()

    def update_instrument_sync_schedule(
        self,
        schedule_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._instrument_sync_schedules().update(schedule_id, payload).to_dict()

    def delete_instrument_sync_schedule(self, schedule_id: str) -> dict[str, str]:
        return self._instrument_sync_schedules().delete(schedule_id)

    def enable_instrument_sync_schedule(self, schedule_id: str) -> dict[str, Any]:
        return self._instrument_sync_schedules().enable(schedule_id).to_dict()

    def disable_instrument_sync_schedule(self, schedule_id: str) -> dict[str, Any]:
        return self._instrument_sync_schedules().disable(schedule_id).to_dict()

    def run_instrument_sync_schedule_now(self, schedule_id: str) -> dict[str, object]:
        return self._instrument_sync_schedules().run_now(schedule_id)

    def instrument_sync_schedule_runs(
        self,
        schedule_id: str,
    ) -> dict[str, list[dict[str, Any]]]:
        return self._instrument_sync_schedules().runs(schedule_id)

    def _metadata(self, spec: DataSourceSpec) -> MetadataStore:
        return MetadataStore(spec.metadata_path)

    def _tasks(self, spec: DataSourceSpec) -> CrawlTaskManager:
        return CrawlTaskManager(self._metadata(spec))

    def _instrument_store(self, source_id: str | None = None) -> InstrumentStore:
        if not self.config.sources:
            raise ValueError("No data sources configured")
        return InstrumentStore(self._metadata(self.config.sources[0]))

    def _instrument_sync(self) -> InstrumentSyncService:
        if self.instrument_sync_service is None:
            self.instrument_sync_service = InstrumentSyncService(
                config=self.config,
                store_factory=lambda: self._instrument_store(None),
            )
        return self.instrument_sync_service

    def _instrument_sync_schedules(self) -> InstrumentSyncScheduleService:
        if self.instrument_sync_schedule_service is None:
            self.instrument_sync_schedule_service = InstrumentSyncScheduleService(
                store=InstrumentSyncScheduleStore(self.config.schedule_db_path),
                config=self.config,
                sync_source=lambda source_id: self.run_instrument_sync(
                    {"source_id": source_id}
                ),
            )
        return self.instrument_sync_schedule_service

    def _validate_source_id(self, source_id: str | None) -> str | None:
        if source_id is None:
            return None
        normalized = source_id.strip()
        if not normalized:
            return None
        self.config.source(normalized)
        return normalized

    def _ensure_instrument_source(
        self,
        record: Any,
        source_id: str | None,
    ) -> None:
        if source_id is not None and record.source_id != source_id:
            raise ValueError(f"Unknown instrument: {record.instrument_id}")

    def _ensure_instruments_source(
        self,
        store: InstrumentStore,
        instrument_ids: list[str],
        source_id: str | None,
    ) -> None:
        if source_id is None:
            return
        for instrument_id in instrument_ids:
            self._ensure_instrument_source(store.get_instrument(instrument_id), source_id)

    @staticmethod
    def _record_symbol(record: Any) -> str:
        symbol = getattr(record, "symbol", None) or getattr(record, "instrument_id", "")
        normalized = str(symbol).strip()
        if not normalized:
            raise ValueError(f"Instrument has no symbol: {getattr(record, 'instrument_id', '')}")
        return normalized

    @staticmethod
    def _target_value(target: Any, key: str) -> Any:
        if isinstance(target, dict):
            return target.get(key)
        return getattr(target, key, None)

    def _schedules(self) -> DataSourceScheduleService:
        if self.schedule_service is None:
            raise ValueError("Scheduler is not configured")
        return self.schedule_service

    @staticmethod
    def _normalize_job_payload(payload: dict[str, Any]) -> dict[str, Any]:
        result = dict(payload)
        for key in ("bars_root", "metadata", "output_dir"):
            if isinstance(result.get(key), str):
                result[key] = Path(result[key])
        return result

    @staticmethod
    def _payload_source_id(payload: dict[str, Any]) -> str | None:
        value = payload.get("source_id")
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _payload_instrument_ids(payload: dict[str, Any]) -> list[str]:
        values = payload.get("instrument_ids")
        if not isinstance(values, list):
            raise ValueError("instrument_ids must be a list")
        return [str(value) for value in values]

    @classmethod
    def _jsonify(cls, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return cls._jsonify(value.model_dump())
        if isinstance(value, dict):
            return {key: cls._jsonify(item) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._jsonify(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if hasattr(value, "value"):
            return value.value
        return value
