from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from backtest.charts.kline_service import KlineCacheService, KlineSource
from backtest.data.catalog import DataCatalog
from backtest.data.jobs import DataSyncJobConfig
from backtest.data.metadata import MetadataStore
from backtest.data.tasks import CrawlTaskManager
from backtest.data_source.config import DataSourceServerConfig, DataSourceSpec
from backtest.data_source.jobs import DataSourceJobRegistry


class DataSourceApi:
    def __init__(
        self,
        config: DataSourceServerConfig,
        job_registry: DataSourceJobRegistry,
    ) -> None:
        self.config = config
        self.job_registry = job_registry
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

    def kline_manifest(self) -> dict[str, Any]:
        return self.kline_service.manifest(default_window_size=self.config.default_window_size)

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

    def tasks(self, source_id: str) -> dict[str, list[dict[str, Any]]]:
        spec = self.config.source(source_id)
        return {"tasks": [self._jsonify(record) for record in self._tasks(spec).list_tasks()]}

    def inventory(self, source_id: str) -> dict[str, list[dict[str, Any]]]:
        spec = self.config.source(source_id)
        return {
            "records": [
                self._jsonify(record)
                for record in DataCatalog(self._metadata(spec)).inventory()
            ]
        }

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

    def _metadata(self, spec: DataSourceSpec) -> MetadataStore:
        return MetadataStore(spec.metadata_path)

    def _tasks(self, spec: DataSourceSpec) -> CrawlTaskManager:
        return CrawlTaskManager(self._metadata(spec))

    @staticmethod
    def _normalize_job_payload(payload: dict[str, Any]) -> dict[str, Any]:
        result = dict(payload)
        for key in ("bars_root", "metadata", "output_dir"):
            if isinstance(result.get(key), str):
                result[key] = Path(result[key])
        return result

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
