from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from typing import Any, Callable

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CachedTaskSummary:
    payload: dict[str, Any]
    cached_at: datetime
    error: str | None = None

    def to_response(self, *, from_cache: bool) -> dict[str, Any]:
        return {
            **self.payload,
            "cached_at": self.cached_at.isoformat(),
            "from_cache": from_cache,
            "refresh_error": self.error,
        }


class CrawlTaskSummaryCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._entries: dict[str, CachedTaskSummary] = {}

    def get(self, source_id: str) -> CachedTaskSummary | None:
        with self._lock:
            return self._entries.get(source_id)

    def put(self, source_id: str, entry: CachedTaskSummary) -> None:
        with self._lock:
            self._entries[source_id] = entry

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class CrawlTaskSummaryRefresher:
    def __init__(
        self,
        *,
        refresh_all: Callable[[], None],
        poll_seconds: float,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be greater than 0")
        self.refresh_all = refresh_all
        self.poll_seconds = poll_seconds
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self, *, refresh_immediately: bool = True) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if refresh_immediately:
            self.tick()
        self._stop.clear()
        self._thread = Thread(target=self._run, daemon=True, name="crawl-task-summary-refresher")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def tick(self) -> None:
        self.refresh_all()

    def _run(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                self.tick()
            except Exception:
                LOGGER.exception("Crawl task summary refresh failed")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
