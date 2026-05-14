from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class DataSourceJobSnapshot:
    job_id: str
    name: str
    status: str
    submitted_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_items: int = 0
    success_count: int = 0
    failed_count: int = 0
    total_rows: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "status": self.status,
            "submitted_at": self.submitted_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "total_items": self.total_items,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "total_rows": self.total_rows,
            "error": self.error,
        }


class DataSourceJobRegistry:
    def __init__(
        self,
        run_job: Callable[[Any], Any],
        *,
        now: Callable[[], datetime] = datetime.now,
        run_inline: bool = False,
    ) -> None:
        self.run_job = run_job
        self.now = now
        self.run_inline = run_inline
        self._lock = threading.Lock()
        self._snapshots: dict[str, DataSourceJobSnapshot] = {}

    def submit(self, config: Any) -> DataSourceJobSnapshot:
        submitted_at = self.now()
        name = self._job_name(config)
        with self._lock:
            job_id = self._job_id(submitted_at, name)
            snapshot = DataSourceJobSnapshot(
                job_id=job_id,
                name=name,
                status="submitted",
                submitted_at=submitted_at,
            )
            self._snapshots[job_id] = snapshot
        if self.run_inline:
            self._run(job_id, config)
        else:
            thread = threading.Thread(target=self._run, args=(job_id, config), daemon=True)
            thread.start()
        return self.get(job_id)

    def list(self) -> list[DataSourceJobSnapshot]:
        with self._lock:
            return sorted(self._snapshots.values(), key=lambda snapshot: snapshot.submitted_at)

    def get(self, job_id: str) -> DataSourceJobSnapshot:
        with self._lock:
            snapshot = self._snapshots.get(job_id)
        if snapshot is None:
            raise ValueError(f"Unknown job: {job_id}")
        return snapshot

    def _run(self, job_id: str, config: Any) -> None:
        started_at = self.now()
        current = self.get(job_id)
        self._store(replace(current, status="running", started_at=started_at, error=None))
        try:
            result = self.run_job(config)
            failed_count = int(getattr(result, "failed_count", 0))
            status = "failed" if failed_count > 0 else "success"
            self._store(
                replace(
                    self.get(job_id),
                    name=getattr(result, "name", current.name),
                    status=status,
                    started_at=getattr(result, "started_at", started_at),
                    finished_at=getattr(result, "finished_at", None) or self.now(),
                    total_items=int(getattr(result, "total_items", 0)),
                    success_count=int(getattr(result, "success_count", 0)),
                    failed_count=failed_count,
                    total_rows=int(getattr(result, "total_rows", 0)),
                    error="One or more job items failed" if failed_count > 0 else None,
                )
            )
        except Exception as exc:
            self._store(
                replace(
                    self.get(job_id),
                    status="failed",
                    finished_at=self.now(),
                    error=str(exc),
                )
            )

    def _store(self, snapshot: DataSourceJobSnapshot) -> None:
        with self._lock:
            self._snapshots[snapshot.job_id] = snapshot

    def _job_id(self, submitted_at: datetime, name: str) -> str:
        base = f"{submitted_at:%Y%m%d%H%M%S}-{self._slug(name)}"
        job_id = base
        counter = 2
        while job_id in self._snapshots:
            job_id = f"{base}-{counter}"
            counter += 1
        return job_id

    @staticmethod
    def _job_name(config: Any) -> str:
        if isinstance(config, dict):
            return str(config.get("name", "data-source-job"))
        return str(getattr(config, "name", "data-source-job"))

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug or "job"
