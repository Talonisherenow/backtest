# Remote Data Source API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a trusted-LAN data-source server that exposes cached K-line data, crawl task state, inventory, job submission, and retry APIs, then let the workbench K-line viewer consume a remote data API base URL.

**Architecture:** Add a focused `backtest.data_source` package with configuration objects, an API facade, a background job registry, and a stdlib `ThreadingHTTPServer` adapter. Keep existing `KlineCacheService`, `DataCatalog`, `CrawlTaskManager`, `DataSyncService`, and `MarketDataJobRunner` as the business logic. Update the K-line viewer fetch helper and workbench CLI so same-origin behavior remains the default while remote data-source mode is opt-in.

**Tech Stack:** Python 3.11+, stdlib `http.server`, Typer, Pydantic job config models, pandas-backed Parquet cache services, pytest, existing HTML/JavaScript K-line viewer template.

---

## File Structure

- Create `backtest/data_source/__init__.py`: export public API classes used by tests and CLI.
- Create `backtest/data_source/config.py`: define source and server configuration plus default source construction.
- Create `backtest/data_source/jobs.py`: maintain an in-process background job registry with injectable runner factory for tests.
- Create `backtest/data_source/api.py`: facade for health, data sources, K-line manifest/bars, tasks, inventory, retry, and job submission/status.
- Create `backtest/data_source/server.py`: stdlib HTTP server routing, JSON serialization, request body parsing, CORS, and error conversion.
- Create `backtest/cli/data_source.py`: Typer command group for `backtest data-source serve`.
- Modify `backtest/cli/app.py`: register the new `data-source` command group.
- Modify `backtest/charts/kline_viewer.py` and `backtest/charts/kline_viewer_template.html`: support `data_api_base_url` in dynamic mode.
- Modify `backtest/charts/workbench_server.py`: pass `data_api_base_url` into the K-line viewer payload.
- Modify `backtest/cli/chart.py`: add `--data-api-base-url` to `serve-workbench`.
- Create `tests/data_source/test_config.py`, `tests/data_source/test_jobs.py`, `tests/data_source/test_api.py`, and `tests/data_source/test_server.py`.
- Modify `tests/charts/test_kline_viewer.py`, `tests/charts/test_workbench_server.py`, and `tests/test_cli_commands.py`.

## Task 1: Data Source Configuration

**Files:**
- Create: `tests/data_source/test_config.py`
- Create: `backtest/data_source/__init__.py`
- Create: `backtest/data_source/config.py`

- [ ] **Step 1: Write failing config tests**

Create `tests/data_source/test_config.py`:

```python
from pathlib import Path

import pytest

from backtest.data_source.config import (
    DataSourceServerConfig,
    DataSourceSpec,
    build_default_source_specs,
)


def test_data_source_spec_serializes_public_metadata(tmp_path: Path):
    bars_root = tmp_path / "bitget" / "bars"
    metadata_path = tmp_path / "bitget" / "metadata.sqlite"
    bars_root.mkdir(parents=True)

    spec = DataSourceSpec(
        source_id="bitget",
        source_label="Bitget",
        asset_class="crypto",
        bars_root=bars_root,
        metadata_path=metadata_path,
        adjust="none",
        catalog_source="ccxt:bitget",
        universe_path=None,
        crawl_jobs=True,
    )

    assert spec.public_dict() == {
        "source_id": "bitget",
        "source_label": "Bitget",
        "asset_class": "crypto",
        "bars": True,
        "crawl_jobs": True,
    }


def test_server_config_rejects_duplicate_source_ids(tmp_path: Path):
    bars_root = tmp_path / "bars"
    bars_root.mkdir()
    source = DataSourceSpec(
        source_id="bitget",
        source_label="Bitget",
        asset_class="crypto",
        bars_root=bars_root,
        metadata_path=tmp_path / "metadata.sqlite",
        adjust="none",
        catalog_source="ccxt:bitget",
    )

    with pytest.raises(ValueError, match="Duplicate data source id"):
        DataSourceServerConfig(sources=[source, source])


def test_build_default_source_specs_skips_disabled_sources(tmp_path: Path):
    bitget_root = tmp_path / "crypto" / "bitget" / "bars"
    a_share_root = tmp_path / "bars"
    universe_path = tmp_path / "a_share_all.csv"
    bitget_root.mkdir(parents=True)
    a_share_root.mkdir()
    universe_path.write_text("symbol,code,name\n000001.SZ,000001,平安银行\n", encoding="utf-8")

    specs = build_default_source_specs(
        bitget_bars_root=bitget_root,
        bitget_metadata=tmp_path / "crypto" / "bitget" / "metadata.sqlite",
        a_share_bars_root=a_share_root,
        a_share_metadata=tmp_path / "metadata.sqlite",
        a_share_universe=universe_path,
        include_bitget=False,
        include_a_share=True,
    )

    assert [spec.source_id for spec in specs] == ["a_share"]
    assert specs[0].adjust == "qfq"
    assert specs[0].catalog_source == "akshare"
    assert specs[0].universe_path == universe_path
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
uv run pytest tests/data_source/test_config.py -q
```

Expected: FAIL because `backtest.data_source` does not exist.

- [ ] **Step 3: Implement config classes**

Create `backtest/data_source/config.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DataSourceSpec:
    source_id: str
    source_label: str
    asset_class: str
    bars_root: Path
    metadata_path: Path
    adjust: str
    catalog_source: str
    universe_path: Path | None = None
    crawl_jobs: bool = True

    def public_dict(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "source_label": self.source_label,
            "asset_class": self.asset_class,
            "bars": True,
            "crawl_jobs": self.crawl_jobs,
        }


@dataclass(frozen=True)
class DataSourceServerConfig:
    sources: list[DataSourceSpec]
    host: str = "127.0.0.1"
    port: int = 8768
    default_window_size: int = 300

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for source in self.sources:
            if source.source_id in seen:
                raise ValueError(f"Duplicate data source id: {source.source_id}")
            seen.add(source.source_id)
            if not source.bars_root.is_dir():
                raise ValueError(f"Bars root does not exist: {source.bars_root}")

    def source(self, source_id: str) -> DataSourceSpec:
        for source in self.sources:
            if source.source_id == source_id:
                return source
        raise ValueError(f"Unknown data source: {source_id}")


def build_default_source_specs(
    *,
    bitget_bars_root: Path,
    bitget_metadata: Path,
    a_share_bars_root: Path,
    a_share_metadata: Path,
    a_share_universe: Path | None,
    include_bitget: bool = True,
    include_a_share: bool = True,
) -> list[DataSourceSpec]:
    specs: list[DataSourceSpec] = []
    if include_bitget:
        specs.append(
            DataSourceSpec(
                source_id="bitget",
                source_label="Bitget",
                asset_class="crypto",
                bars_root=bitget_bars_root,
                metadata_path=bitget_metadata,
                adjust="none",
                catalog_source="ccxt:bitget",
            )
        )
    if include_a_share:
        universe_path = a_share_universe if a_share_universe and a_share_universe.exists() else None
        specs.append(
            DataSourceSpec(
                source_id="a_share",
                source_label="A-share",
                asset_class="equity",
                bars_root=a_share_bars_root,
                metadata_path=a_share_metadata,
                adjust="qfq",
                catalog_source="akshare",
                universe_path=universe_path,
            )
        )
    if not specs:
        raise ValueError("At least one data source must be enabled")
    return specs
```

Create `backtest/data_source/__init__.py`:

```python
from backtest.data_source.config import (
    DataSourceServerConfig,
    DataSourceSpec,
    build_default_source_specs,
)

__all__ = [
    "DataSourceServerConfig",
    "DataSourceSpec",
    "build_default_source_specs",
]
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
uv run pytest tests/data_source/test_config.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/data_source/__init__.py backtest/data_source/config.py tests/data_source/test_config.py
git commit -m "feat: add data source server config"
```

## Task 2: Background Job Registry

**Files:**
- Create: `tests/data_source/test_jobs.py`
- Create: `backtest/data_source/jobs.py`
- Modify: `backtest/data_source/__init__.py`

- [ ] **Step 1: Write failing job registry tests**

Create `tests/data_source/test_jobs.py`:

```python
from datetime import datetime
from pathlib import Path

from backtest.data.jobs import DataSyncJobConfig, JobResult
from backtest.data_source.jobs import DataSourceJobRegistry


def _job_config(tmp_path: Path) -> DataSyncJobConfig:
    return DataSyncJobConfig(
        name="crypto-bitget-core",
        source="ccxt",
        exchange="bitget",
        symbols=["BTC/USDT"],
        frequencies=["1d"],
        adjust="none",
        start_date="2026-05-01",
        end_date="2026-05-02",
        bars_root=tmp_path / "bars",
        metadata=tmp_path / "metadata.sqlite",
        output_dir=tmp_path / "runs",
    )


def test_registry_submits_and_records_success(tmp_path: Path):
    calls: list[DataSyncJobConfig] = []

    def run_job(config: DataSyncJobConfig) -> JobResult:
        calls.append(config)
        return JobResult(
            name=config.name,
            started_at=datetime(2026, 5, 15, 10, 0, 1),
            finished_at=datetime(2026, 5, 15, 10, 0, 2),
        )

    registry = DataSourceJobRegistry(
        run_job=run_job,
        now=lambda: datetime(2026, 5, 15, 10, 0, 0),
        run_inline=True,
    )

    snapshot = registry.submit(_job_config(tmp_path))
    stored = registry.get(snapshot.job_id)

    assert snapshot.status == "success"
    assert stored.status == "success"
    assert stored.name == "crypto-bitget-core"
    assert stored.error is None
    assert calls[0].name == "crypto-bitget-core"


def test_registry_records_failed_job(tmp_path: Path):
    def run_job(config: DataSyncJobConfig) -> JobResult:
        raise RuntimeError("exchange unavailable")

    registry = DataSourceJobRegistry(
        run_job=run_job,
        now=lambda: datetime(2026, 5, 15, 10, 0, 0),
        run_inline=True,
    )

    snapshot = registry.submit(_job_config(tmp_path))

    assert snapshot.status == "failed"
    assert snapshot.error == "exchange unavailable"
    assert registry.list()[0].job_id == snapshot.job_id
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
uv run pytest tests/data_source/test_jobs.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `backtest.data_source.jobs`.

- [ ] **Step 3: Implement job registry**

Create `backtest/data_source/jobs.py`:

```python
from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from backtest.data.jobs import DataSyncJobConfig, JobResult


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
        *,
        run_job: Callable[[DataSyncJobConfig], JobResult],
        now: Callable[[], datetime] = datetime.now,
        run_inline: bool = False,
    ) -> None:
        self._run_job = run_job
        self._now = now
        self._run_inline = run_inline
        self._lock = threading.Lock()
        self._jobs: dict[str, DataSourceJobSnapshot] = {}

    def submit(self, config: DataSyncJobConfig) -> DataSourceJobSnapshot:
        submitted_at = self._now()
        job_id = f"{submitted_at.strftime('%Y%m%dT%H%M%S')}-{_slug(config.name)}"
        snapshot = DataSourceJobSnapshot(
            job_id=job_id,
            name=config.name,
            status="submitted",
            submitted_at=submitted_at,
        )
        self._store(snapshot)
        if self._run_inline:
            self._execute(job_id, config)
        else:
            thread = threading.Thread(target=self._execute, args=(job_id, config), daemon=True)
            thread.start()
        return self.get(job_id)

    def list(self) -> list[DataSourceJobSnapshot]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda item: item.submitted_at)

    def get(self, job_id: str) -> DataSourceJobSnapshot:
        with self._lock:
            snapshot = self._jobs.get(job_id)
        if snapshot is None:
            raise ValueError(f"Unknown job id: {job_id}")
        return snapshot

    def _execute(self, job_id: str, config: DataSyncJobConfig) -> None:
        started = self._now()
        self._replace(job_id, status="running", started_at=started)
        try:
            result = self._run_job(config)
            self._replace(
                job_id,
                status="success" if result.failed_count == 0 else "failed",
                finished_at=result.finished_at or self._now(),
                total_items=result.total_items,
                success_count=result.success_count,
                failed_count=result.failed_count,
                total_rows=result.total_rows,
                error=None if result.failed_count == 0 else "One or more job items failed",
            )
        except Exception as exc:
            self._replace(job_id, status="failed", finished_at=self._now(), error=str(exc))

    def _store(self, snapshot: DataSourceJobSnapshot) -> None:
        with self._lock:
            self._jobs[snapshot.job_id] = snapshot

    def _replace(self, job_id: str, **changes: object) -> None:
        snapshot = self.get(job_id)
        data = snapshot.__dict__.copy()
        data.update(changes)
        self._store(DataSourceJobSnapshot(**data))


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return slug or "job"
```

Modify `backtest/data_source/__init__.py`:

```python
from backtest.data_source.config import (
    DataSourceServerConfig,
    DataSourceSpec,
    build_default_source_specs,
)
from backtest.data_source.jobs import DataSourceJobRegistry, DataSourceJobSnapshot

__all__ = [
    "DataSourceJobRegistry",
    "DataSourceJobSnapshot",
    "DataSourceServerConfig",
    "DataSourceSpec",
    "build_default_source_specs",
]
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
uv run pytest tests/data_source/test_jobs.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/data_source/__init__.py backtest/data_source/jobs.py tests/data_source/test_jobs.py
git commit -m "feat: add data source job registry"
```

## Task 3: Data Source API Facade

**Files:**
- Create: `tests/data_source/test_api.py`
- Create: `backtest/data_source/api.py`
- Modify: `backtest/data_source/__init__.py`

- [ ] **Step 1: Write failing API facade tests**

Create `tests/data_source/test_api.py`:

```python
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from backtest.core.contracts import CatalogRecord
from backtest.core.enums import AdjustMode, Frequency
from backtest.data.catalog import DataCatalog
from backtest.data.jobs import JobResult
from backtest.data.metadata import MetadataStore
from backtest.data.store import ParquetBarStore
from backtest.data.tasks import CrawlTaskManager
from backtest.data_source.api import DataSourceApi
from backtest.data_source.config import DataSourceServerConfig, DataSourceSpec
from backtest.data_source.jobs import DataSourceJobRegistry


def _write_cached_bars(root: Path, symbol: str = "BTC/USDT") -> None:
    ParquetBarStore(root).write_bars(
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-05-01", "2026-05-02", "2026-05-03"]),
                "symbol": [symbol] * 3,
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.5, 101.5, 102.5],
                "volume": [10.0, 11.0, 12.0],
                "amount": [1000.0, 1100.0, 1200.0],
                "frequency": ["1d"] * 3,
                "adjust": ["none"] * 3,
            }
        )
    )


def _api(tmp_path: Path, *, run_inline: bool = True) -> DataSourceApi:
    bars_root = tmp_path / "bitget" / "bars"
    metadata_path = tmp_path / "bitget" / "metadata.sqlite"
    bars_root.mkdir(parents=True)
    _write_cached_bars(bars_root)
    metadata = MetadataStore(metadata_path)
    catalog = DataCatalog(metadata)
    tasks = CrawlTaskManager(metadata)
    task_id = tasks.create_task(
        "BTC/USDT",
        Frequency.DAILY,
        AdjustMode.NONE,
        date(2026, 5, 1),
        date(2026, 5, 3),
        "ccxt:bitget",
    )
    tasks.mark_running(task_id)
    tasks.mark_success(task_id)
    written_path = next(bars_root.glob("frequency=1d/adjust=none/symbol=BTC%2FUSDT/year=2026/bars.parquet"))
    catalog_record = CatalogRecord(
        symbol="BTC/USDT",
        frequency=Frequency.DAILY,
        adjust=AdjustMode.NONE,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 3),
        rows=3,
        source="ccxt:bitget",
        cache_path=written_path,
        updated_at=datetime(2026, 5, 4, 9, 0, 0),
    )
    catalog.upsert(catalog_record)
    assert catalog_record.rows == 3
    config = DataSourceServerConfig(
        sources=[
            DataSourceSpec(
                source_id="bitget",
                source_label="Bitget",
                asset_class="crypto",
                bars_root=bars_root,
                metadata_path=metadata_path,
                adjust="none",
                catalog_source="ccxt:bitget",
            )
        ]
    )

    def run_job(job_config):
        return JobResult(
            name=job_config.name,
            started_at=datetime(2026, 5, 15, 10, 0, 1),
            finished_at=datetime(2026, 5, 15, 10, 0, 2),
        )

    return DataSourceApi(
        config=config,
        job_registry=DataSourceJobRegistry(
            run_job=run_job,
            now=lambda: datetime(2026, 5, 15, 10, 0, 0),
            run_inline=run_inline,
        ),
    )


def test_api_exposes_sources_manifest_and_bars(tmp_path: Path):
    api = _api(tmp_path)

    assert api.health()["status"] == "ok"
    assert api.data_sources()["sources"][0]["source_id"] == "bitget"
    assert api.kline_manifest()["sources"][0]["symbols"][0]["symbol"] == "BTC/USDT"
    bars = api.kline_bars(
        source_id="bitget",
        symbol="BTC/USDT",
        frequency="1d",
        adjust="none",
        limit=2,
        anchor="latest",
    )

    assert bars["source_id"] == "bitget"
    assert bars["loaded_rows"] == 2
    assert [bar["date"] for bar in bars["bars"]] == ["2026-05-02", "2026-05-03"]


def test_api_exposes_tasks_inventory_retry_and_jobs(tmp_path: Path):
    api = _api(tmp_path)

    assert api.tasks("bitget")["tasks"][0]["status"] == "success"
    assert api.inventory("bitget")["records"][0]["rows"] == 3
    retry = api.retry_failed("bitget")
    assert retry == {"queued": 0, "task_ids": []}

    submitted = api.submit_job(
        {
            "name": "crypto-bitget-core",
            "source": "ccxt",
            "exchange": "bitget",
            "symbols": ["BTC/USDT"],
            "frequencies": ["1d"],
            "adjust": "none",
            "start_date": "2026-05-01",
            "end_date": "2026-05-03",
            "bars_root": str(tmp_path / "bitget" / "bars"),
            "metadata": str(tmp_path / "bitget" / "metadata.sqlite"),
            "output_dir": str(tmp_path / "runs"),
        }
    )

    assert submitted["status"] == "success"
    assert api.job(submitted["job_id"])["job_id"] == submitted["job_id"]
    assert api.jobs()["jobs"][0]["name"] == "crypto-bitget-core"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
uv run pytest tests/data_source/test_api.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `backtest.data_source.api`.

- [ ] **Step 3: Implement API facade**

Create `backtest/data_source/api.py`:

```python
from __future__ import annotations

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
    def __init__(self, *, config: DataSourceServerConfig, job_registry: DataSourceJobRegistry) -> None:
        self.config = config
        self.job_registry = job_registry
        self._kline_service = KlineCacheService(
            sources=[
                KlineSource(
                    source.source_id,
                    source.source_label,
                    source.bars_root,
                    adjust=source.adjust,
                    universe_path=source.universe_path,
                )
                for source in config.sources
            ]
        )

    def health(self) -> dict[str, str]:
        return {"status": "ok", "service": "backtest-data-source"}

    def data_sources(self) -> dict[str, list[dict[str, object]]]:
        return {"sources": [source.public_dict() for source in self.config.sources]}

    def kline_manifest(self) -> dict[str, Any]:
        return self._kline_service.manifest(default_window_size=self.config.default_window_size)

    def kline_bars(
        self,
        *,
        source_id: str,
        symbol: str,
        frequency: str,
        adjust: str | None,
        limit: int = 300,
        offset: int | None = None,
        start: str | None = None,
        anchor: str | None = None,
    ) -> dict[str, Any]:
        return self._kline_service.bars(
            source_id=source_id,
            symbol=symbol,
            frequency=frequency,
            adjust=adjust,
            limit=limit,
            offset=offset,
            start=start,
            anchor=anchor,
        )

    def tasks(self, source_id: str) -> dict[str, list[dict[str, object]]]:
        manager = self._task_manager(source_id)
        return {"tasks": [_task_to_dict(record) for record in manager.list_tasks()]}

    def inventory(self, source_id: str) -> dict[str, list[dict[str, object]]]:
        catalog = DataCatalog(self._metadata(source_id))
        return {"records": [_catalog_to_dict(record) for record in catalog.inventory()]}

    def retry_failed(self, source_id: str) -> dict[str, object]:
        manager = self._task_manager(source_id)
        task_ids: list[int] = []
        for task in manager.failed_tasks():
            if task.task_id is None:
                continue
            manager.mark_retrying(task.task_id)
            task_ids.append(task.task_id)
        return {"queued": len(task_ids), "task_ids": task_ids}

    def submit_job(self, payload: dict[str, Any]) -> dict[str, object]:
        config = DataSyncJobConfig.model_validate(_normalize_job_paths(payload))
        snapshot = self.job_registry.submit(config)
        return snapshot.to_dict()

    def jobs(self) -> dict[str, list[dict[str, object]]]:
        return {"jobs": [snapshot.to_dict() for snapshot in self.job_registry.list()]}

    def job(self, job_id: str) -> dict[str, object]:
        return self.job_registry.get(job_id).to_dict()

    def _source(self, source_id: str) -> DataSourceSpec:
        return self.config.source(source_id)

    def _metadata(self, source_id: str) -> MetadataStore:
        return MetadataStore(self._source(source_id).metadata_path)

    def _task_manager(self, source_id: str) -> CrawlTaskManager:
        return CrawlTaskManager(self._metadata(source_id))


def _normalize_job_paths(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    for key in ("bars_root", "metadata", "output_dir"):
        if key in normalized:
            normalized[key] = Path(normalized[key])
    return normalized


def _task_to_dict(record) -> dict[str, object]:
    return {
        "task_id": record.task_id,
        "symbol": record.symbol,
        "frequency": record.frequency.value,
        "adjust": record.adjust.value,
        "start_date": record.start_date.isoformat(),
        "end_date": record.end_date.isoformat(),
        "source": record.source,
        "status": record.status,
        "attempts": record.attempts,
        "last_error": record.last_error,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
    }


def _catalog_to_dict(record) -> dict[str, object]:
    return {
        "symbol": record.symbol,
        "frequency": record.frequency.value,
        "adjust": record.adjust.value,
        "source": record.source,
        "start_date": record.start_date.isoformat(),
        "end_date": record.end_date.isoformat(),
        "rows": record.rows,
        "cache_path": str(record.cache_path),
        "quality_status": record.quality_status,
        "updated_at": record.updated_at.isoformat(),
    }
```

Modify `backtest/data_source/__init__.py`:

```python
from backtest.data_source.api import DataSourceApi
from backtest.data_source.config import (
    DataSourceServerConfig,
    DataSourceSpec,
    build_default_source_specs,
)
from backtest.data_source.jobs import DataSourceJobRegistry, DataSourceJobSnapshot

__all__ = [
    "DataSourceApi",
    "DataSourceJobRegistry",
    "DataSourceJobSnapshot",
    "DataSourceServerConfig",
    "DataSourceSpec",
    "build_default_source_specs",
]
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
uv run pytest tests/data_source/test_api.py tests/data_source/test_config.py tests/data_source/test_jobs.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/data_source/__init__.py backtest/data_source/api.py tests/data_source/test_api.py
git commit -m "feat: add data source api facade"
```

## Task 4: HTTP Data Source Server

**Files:**
- Create: `tests/data_source/test_server.py`
- Create: `backtest/data_source/server.py`

- [ ] **Step 1: Write failing HTTP server tests**

Create `tests/data_source/test_server.py`:

```python
import json
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd

from backtest.data.jobs import JobResult
from backtest.data.store import ParquetBarStore
from backtest.data_source.api import DataSourceApi
from backtest.data_source.config import DataSourceServerConfig, DataSourceSpec
from backtest.data_source.jobs import DataSourceJobRegistry
from backtest.data_source.server import make_data_source_handler


def _api(tmp_path: Path) -> DataSourceApi:
    bars_root = tmp_path / "bitget" / "bars"
    bars_root.mkdir(parents=True)
    ParquetBarStore(bars_root).write_bars(
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-05-01", "2026-05-02"]),
                "symbol": ["BTC/USDT", "BTC/USDT"],
                "open": [100.0, 101.0],
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.5, 101.5],
                "volume": [10.0, 11.0],
                "amount": [1000.0, 1100.0],
                "frequency": ["1d", "1d"],
                "adjust": ["none", "none"],
            }
        )
    )
    config = DataSourceServerConfig(
        sources=[
            DataSourceSpec(
                source_id="bitget",
                source_label="Bitget",
                asset_class="crypto",
                bars_root=bars_root,
                metadata_path=tmp_path / "metadata.sqlite",
                adjust="none",
                catalog_source="ccxt:bitget",
            )
        ]
    )
    registry = DataSourceJobRegistry(
        run_job=lambda config: JobResult(
            name=config.name,
            started_at=datetime(2026, 5, 15, 10, 0, 1),
            finished_at=datetime(2026, 5, 15, 10, 0, 2),
        ),
        now=lambda: datetime(2026, 5, 15, 10, 0, 0),
        run_inline=True,
    )
    return DataSourceApi(config=config, job_registry=registry)


def _read_json(server, path: str) -> dict:
    with urlopen(f"http://127.0.0.1:{server.server_port}{path}", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_http_server_serves_health_manifest_bars_and_cors(tmp_path: Path):
    from http.server import ThreadingHTTPServer
    from threading import Thread

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_data_source_handler(_api(tmp_path)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        health = _read_json(server, "/api/health")
        manifest = _read_json(server, "/api/kline/manifest")
        bars = _read_json(
            server,
            "/api/kline/bars?source_id=bitget&symbol=BTC%2FUSDT&frequency=1d&adjust=none&limit=1",
        )
        request = Request(f"http://127.0.0.1:{server.server_port}/api/data/jobs", method="OPTIONS")
        with urlopen(request, timeout=5) as response:
            assert response.status == HTTPStatus.NO_CONTENT
            assert response.headers["Access-Control-Allow-Origin"] == "*"

        assert health["status"] == "ok"
        assert manifest["sources"][0]["source_id"] == "bitget"
        assert bars["loaded_rows"] == 1
    finally:
        server.shutdown()
        server.server_close()


def test_http_server_submits_job_and_reports_bad_route(tmp_path: Path):
    from http.server import ThreadingHTTPServer
    from threading import Thread

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_data_source_handler(_api(tmp_path)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = json.dumps(
            {
                "name": "crypto-bitget-core",
                "source": "ccxt",
                "exchange": "bitget",
                "symbols": ["BTC/USDT"],
                "frequencies": ["1d"],
                "adjust": "none",
                "start_date": "2026-05-01",
                "end_date": "2026-05-02",
                "bars_root": str(tmp_path / "bitget" / "bars"),
                "metadata": str(tmp_path / "metadata.sqlite"),
                "output_dir": str(tmp_path / "runs"),
            }
        ).encode("utf-8")
        request = Request(
            f"http://127.0.0.1:{server.server_port}/api/data/jobs",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            submitted = json.loads(response.read().decode("utf-8"))

        assert submitted["name"] == "crypto-bitget-core"
        assert submitted["status"] == "success"

        try:
            _read_json(server, "/api/missing")
        except HTTPError as exc:
            assert exc.code == HTTPStatus.NOT_FOUND
            assert json.loads(exc.read().decode("utf-8"))["error"] == "Not found"
    finally:
        server.shutdown()
        server.server_close()
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
uv run pytest tests/data_source/test_server.py -q
```

Expected: FAIL with `ModuleNotFoundError` for `backtest.data_source.server`.

- [ ] **Step 3: Implement HTTP handler and serve function**

Create `backtest/data_source/server.py`:

```python
from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from backtest.data_source.api import DataSourceApi


def serve_data_source_api(*, api: DataSourceApi, host: str = "127.0.0.1", port: int = 8768) -> None:
    server = ThreadingHTTPServer((host, port), make_data_source_handler(api))
    print(f"Serving data source API at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def make_data_source_handler(api: DataSourceApi):
    class DataSourceHandler(BaseHTTPRequestHandler):
        def do_OPTIONS(self) -> None:
            self._send_bytes(b"", "application/json; charset=utf-8", status=HTTPStatus.NO_CONTENT)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            try:
                if parsed.path == "/api/health":
                    self._send_json(api.health())
                    return
                if parsed.path == "/api/data-sources":
                    self._send_json(api.data_sources())
                    return
                if parsed.path == "/api/kline/manifest":
                    self._send_json(api.kline_manifest())
                    return
                if parsed.path == "/api/kline/bars":
                    self._send_json(
                        api.kline_bars(
                            source_id=self._required(params, "source_id"),
                            symbol=unquote(self._required(params, "symbol")),
                            frequency=self._required(params, "frequency"),
                            adjust=self._optional(params, "adjust"),
                            limit=self._int_param(params, "limit", api.config.default_window_size),
                            offset=self._optional_int(params, "offset"),
                            start=self._optional(params, "start"),
                            anchor=self._optional(params, "anchor", "latest"),
                        )
                    )
                    return
                if parsed.path == "/api/data/tasks":
                    self._send_json(api.tasks(self._required(params, "source_id")))
                    return
                if parsed.path == "/api/data/inventory":
                    self._send_json(api.inventory(self._required(params, "source_id")))
                    return
                if parsed.path == "/api/data/jobs":
                    self._send_json(api.jobs())
                    return
                if parsed.path.startswith("/api/data/jobs/"):
                    self._send_json(api.job(parsed.path.rsplit("/", 1)[-1]))
                    return
                self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/data/jobs":
                    self._send_json(api.submit_job(self._json_body()))
                    return
                if parsed.path == "/api/data/retry-failed":
                    payload = self._json_body()
                    self._send_json(api.retry_failed(str(payload.get("source_id", ""))))
                    return
                self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _json_body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Malformed JSON body: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload

        def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self._send_bytes(body, "application/json; charset=utf-8", status=status)

        def _send_bytes(self, body: bytes, content_type: str, status: HTTPStatus) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()
            self.wfile.write(body)

        @staticmethod
        def _required(params: dict[str, list[str]], name: str) -> str:
            value = DataSourceHandler._optional(params, name)
            if value is None:
                raise ValueError(f"Missing required parameter: {name}")
            return value

        @staticmethod
        def _optional(params: dict[str, list[str]], name: str, default: str | None = None) -> str | None:
            values = params.get(name)
            if not values:
                return default
            return values[0]

        @staticmethod
        def _int_param(params: dict[str, list[str]], name: str, default: int) -> int:
            value = DataSourceHandler._optional(params, name)
            return int(value) if value not in {None, ""} else default

        @staticmethod
        def _optional_int(params: dict[str, list[str]], name: str) -> int | None:
            value = DataSourceHandler._optional(params, name)
            return int(value) if value not in {None, ""} else None

    return DataSourceHandler
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
uv run pytest tests/data_source/test_server.py tests/data_source/test_api.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/data_source/server.py tests/data_source/test_server.py
git commit -m "feat: serve data source api over http"
```

## Task 5: Data Source CLI

**Files:**
- Modify: `tests/test_cli_commands.py`
- Create: `backtest/cli/data_source.py`
- Modify: `backtest/cli/app.py`

- [ ] **Step 1: Add failing CLI test**

Append to `tests/test_cli_commands.py`:

```python
def test_data_source_serve_cli_passes_server_options(tmp_path: Path, monkeypatch):
    from backtest.cli import data_source as data_source_cli

    bitget_root = tmp_path / "crypto" / "bitget" / "bars"
    a_share_root = tmp_path / "bars"
    universe_path = tmp_path / "a_share_all.csv"
    bitget_root.mkdir(parents=True)
    a_share_root.mkdir()
    universe_path.write_text("symbol,code,name\n000001.SZ,000001,平安银行\n", encoding="utf-8")
    captured = {}

    def fake_serve_data_source_api(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(data_source_cli, "serve_data_source_api", fake_serve_data_source_api)

    result = CliRunner().invoke(
        app,
        [
            "data-source",
            "serve",
            "--bitget-bars-root",
            str(bitget_root),
            "--bitget-metadata",
            str(tmp_path / "crypto" / "bitget" / "metadata.sqlite"),
            "--a-share-bars-root",
            str(a_share_root),
            "--a-share-metadata",
            str(tmp_path / "metadata.sqlite"),
            "--a-share-universe",
            str(universe_path),
            "--host",
            "0.0.0.0",
            "--port",
            "8768",
            "--window-size",
            "250",
        ],
    )

    assert result.exit_code == 0
    assert "Starting data source API" in result.output
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8768
    assert captured["api"].config.default_window_size == 250
    assert [source.source_id for source in captured["api"].config.sources] == ["bitget", "a_share"]
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
uv run pytest tests/test_cli_commands.py::test_data_source_serve_cli_passes_server_options -q
```

Expected: FAIL because `backtest.cli.data_source` does not exist or `data-source` is not registered.

- [ ] **Step 3: Implement CLI command**

Create `backtest/cli/data_source.py`:

```python
from pathlib import Path

import typer

from backtest.cli.data import _provider_for_source
from backtest.data.catalog import DataCatalog
from backtest.data.jobs import MarketDataJobRunner
from backtest.data.metadata import MetadataStore
from backtest.data.service import DataSyncService
from backtest.data.store import ParquetBarStore
from backtest.data.tasks import CrawlTaskManager
from backtest.data_source.api import DataSourceApi
from backtest.data_source.config import DataSourceServerConfig, build_default_source_specs
from backtest.data_source.jobs import DataSourceJobRegistry
from backtest.data_source.server import serve_data_source_api

app = typer.Typer(help="Serve remote market data source APIs")


@app.command("serve")
def serve(
    bitget_bars_root: Path = typer.Option(Path("data/crypto/bitget/bars"), "--bitget-bars-root", file_okay=False),
    bitget_metadata: Path = typer.Option(Path("data/crypto/bitget/metadata.sqlite"), "--bitget-metadata"),
    a_share_bars_root: Path = typer.Option(Path("data/bars"), "--a-share-bars-root", file_okay=False),
    a_share_metadata: Path = typer.Option(Path("data/metadata.sqlite"), "--a-share-metadata"),
    a_share_universe: Path | None = typer.Option(Path("data/universe/a_share_all_20260504.csv"), "--a-share-universe"),
    include_bitget: bool = typer.Option(True, "--include-bitget/--no-bitget"),
    include_a_share: bool = typer.Option(True, "--include-a-share/--no-a-share"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8768, "--port", min=1, max=65535),
    window_size: int = typer.Option(300, "--window-size", min=1),
) -> None:
    try:
        sources = build_default_source_specs(
            bitget_bars_root=bitget_bars_root,
            bitget_metadata=bitget_metadata,
            a_share_bars_root=a_share_bars_root,
            a_share_metadata=a_share_metadata,
            a_share_universe=a_share_universe,
            include_bitget=include_bitget,
            include_a_share=include_a_share,
        )
        config = DataSourceServerConfig(
            sources=sources,
            host=host,
            port=port,
            default_window_size=window_size,
        )
        registry = DataSourceJobRegistry(run_job=_run_data_job)
        api = DataSourceApi(config=config, job_registry=registry)
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Starting data source API with {len(sources)} sources at http://{host}:{port}")
    serve_data_source_api(api=api, host=host, port=port)


def _run_data_job(config):
    metadata = MetadataStore(config.metadata)
    catalog = DataCatalog(metadata)
    service = DataSyncService(
        provider=_provider_for_source(
            config.source,
            config.exchange,
            page_delay_seconds=config.page_delay_seconds,
        ),
        store=ParquetBarStore(config.bars_root),
        catalog=catalog,
        tasks=CrawlTaskManager(metadata),
    )
    return MarketDataJobRunner(service=service, catalog=catalog).run(config)
```

Modify `backtest/cli/app.py`:

```python
import typer

from backtest.cli import chart, data, data_source, run, validate

app = typer.Typer(help="A Share backtest research CLI")
app.add_typer(run.app)
app.add_typer(data.app, name="data")
app.add_typer(data_source.app, name="data-source")
app.add_typer(chart.app, name="chart")
app.add_typer(validate.app, name="validate")
```

- [ ] **Step 4: Run CLI test and verify GREEN**

Run:

```bash
uv run pytest tests/test_cli_commands.py::test_data_source_serve_cli_passes_server_options -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/cli/app.py backtest/cli/data_source.py tests/test_cli_commands.py
git commit -m "feat: add data source api cli"
```

## Task 6: Remote K-line Viewer Fetch Base

**Files:**
- Modify: `tests/charts/test_kline_viewer.py`
- Modify: `backtest/charts/kline_viewer_template.html`
- Modify: `backtest/charts/kline_viewer.py`

- [ ] **Step 1: Add failing viewer tests**

Append to `tests/charts/test_kline_viewer.py`:

```python
def test_render_kline_viewer_supports_remote_data_api_base_url():
    html = render_kline_viewer_html(
        {
            "mode": "dynamic",
            "data_api_base_url": "http://192.168.1.10:8768",
            "default_window_size": 300,
        }
    )

    assert '"data_api_base_url":"http://192.168.1.10:8768"' in html
    assert "function apiUrl(path)" in html
    assert 'apiUrl("/api/kline/manifest")' in html
    assert 'apiUrl(`/api/kline/bars?${params.toString()}`)' in html
```

- [ ] **Step 2: Run test and verify RED**

Run:

```bash
uv run pytest tests/charts/test_kline_viewer.py::test_render_kline_viewer_supports_remote_data_api_base_url -q
```

Expected: FAIL because the template still fetches `"/api/manifest"` and direct same-origin bars URLs instead of using `apiUrl`.

- [ ] **Step 3: Implement `apiUrl` helper in both template sources**

Modify the script in `backtest/charts/kline_viewer_template.html` and the embedded template in `backtest/charts/kline_viewer.py` with the same logic:

```javascript
    function apiUrl(path) {
      const baseUrl = String(payload.data_api_base_url || "").replace(/\/+$/, "");
      if (!baseUrl) {
        return path;
      }
      return `${baseUrl}${path}`;
    }
```

Change manifest fetch:

```javascript
        const response = await fetch(apiUrl("/api/kline/manifest"), { cache: "no-store" });
```

Change bars fetch:

```javascript
        const response = await fetch(apiUrl(`/api/kline/bars?${params.toString()}`), { cache: "no-store" });
```

Task 8 must add local aliases for these new same-origin paths so standalone local K-line servers and workbench K-line pages keep working without a remote base URL.

- [ ] **Step 4: Run viewer tests and verify GREEN**

Run:

```bash
uv run pytest tests/charts/test_kline_viewer.py::test_render_kline_viewer_supports_remote_data_api_base_url tests/charts/test_kline_viewer.py::test_write_kline_viewer_supports_dynamic_api_mode -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/charts/kline_viewer.py backtest/charts/kline_viewer_template.html tests/charts/test_kline_viewer.py
git commit -m "feat: support remote kline data api"
```

## Task 7: Workbench Remote Data API Option

**Files:**
- Modify: `tests/charts/test_workbench_server.py`
- Modify: `tests/test_cli_commands.py`
- Modify: `backtest/charts/workbench_server.py`
- Modify: `backtest/cli/chart.py`

- [ ] **Step 1: Add failing workbench server test**

Modify `tests/charts/test_workbench_server.py`:

```python
from backtest.charts.workbench_server import build_kline_shell_payload, render_workbench_index_html


def test_render_workbench_index_html_links_both_chart_apps():
    html = render_workbench_index_html()

    assert "Backtest Workbench" in html
    assert 'href="/strategy-results"' in html
    assert "Strategy Results" in html
    assert 'href="/kline"' in html
    assert "K-line Viewer" in html


def test_build_kline_shell_payload_includes_remote_data_api_base_url():
    payload = build_kline_shell_payload(default_window_size=250, data_api_base_url="http://192.168.1.10:8768")

    assert payload["mode"] == "dynamic"
    assert payload["default_window_size"] == 250
    assert payload["links"] == {"workbench_home": "/"}
    assert payload["data_api_base_url"] == "http://192.168.1.10:8768"
```

- [ ] **Step 2: Add failing CLI delegation assertion**

Modify `tests/test_cli_commands.py::test_chart_serve_workbench_cli_starts_combined_server` by adding the option:

```python
            "--data-api-base-url",
            "http://192.168.1.10:8768",
```

Add the assertion:

```python
    assert captured["data_api_base_url"] == "http://192.168.1.10:8768"
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
uv run pytest tests/charts/test_workbench_server.py::test_build_kline_shell_payload_includes_remote_data_api_base_url tests/test_cli_commands.py::test_chart_serve_workbench_cli_starts_combined_server -q
```

Expected: FAIL because `build_kline_shell_payload` and `--data-api-base-url` do not exist.

- [ ] **Step 4: Implement workbench payload and CLI option**

Modify `backtest/charts/workbench_server.py`:

```python
def build_kline_shell_payload(
    *,
    default_window_size: int,
    data_api_base_url: str | None = None,
) -> dict:
    payload = {
        "mode": "dynamic",
        "default_window_size": default_window_size,
        "links": {"workbench_home": "/"},
    }
    if data_api_base_url:
        payload["data_api_base_url"] = data_api_base_url.rstrip("/")
    return payload
```

Update `serve_chart_workbench` signature:

```python
def serve_chart_workbench(
    *,
    kline_sources: list[KlineSource],
    results_roots: list[Path],
    bars_root: Path,
    host: str = "127.0.0.1",
    port: int = 8767,
    default_window_size: int = 300,
    data_api_base_url: str | None = None,
) -> None:
```

Use the helper:

```python
    kline_html = render_kline_viewer_html(
        build_kline_shell_payload(
            default_window_size=default_window_size,
            data_api_base_url=data_api_base_url,
        )
    ).encode("utf-8")
```

Modify `backtest/cli/chart.py` in `serve_workbench`:

```python
    data_api_base_url: str | None = typer.Option(
        None,
        "--data-api-base-url",
        help="Optional remote data source API base URL for K-line data",
    ),
```

Pass it through:

```python
        data_api_base_url=data_api_base_url,
```

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```bash
uv run pytest tests/charts/test_workbench_server.py tests/test_cli_commands.py::test_chart_serve_workbench_cli_starts_combined_server -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backtest/charts/workbench_server.py backtest/cli/chart.py tests/charts/test_workbench_server.py tests/test_cli_commands.py
git commit -m "feat: pass remote data api to workbench"
```

## Task 8: Local Endpoint Compatibility And Integration Checks

**Files:**
- Modify: `backtest/charts/kline_server.py`
- Modify: `backtest/charts/workbench_server.py`
- Modify: `docs/market-data-operations.md`

- [ ] **Step 1: Add compatibility expectation**

Add aliases in both local chart servers so old and new paths both work. Existing clients may still call `/api/manifest` and `/api/bars`, while the updated viewer calls `/api/kline/manifest` and `/api/kline/bars` when it is served from the same origin.

Expected local aliases:

```text
GET /api/manifest
GET /api/bars
GET /api/kline/manifest
GET /api/kline/bars
```

- [ ] **Step 2: Implement alias routes**

Modify `backtest/charts/kline_server.py`:

```python
            if parsed.path in {"/api/manifest", "/api/kline/manifest"}:
                self._send_json(service.manifest(default_window_size=default_window_size))
                return
            if parsed.path in {"/api/bars", "/api/kline/bars"}:
                self._handle_bars(parsed.query)
                return
```

Modify `backtest/charts/workbench_server.py` similarly:

```python
            if parsed.path in {"/api/manifest", "/api/kline/manifest"}:
                self._send_json(kline_service.manifest(default_window_size=default_window_size))
                return
            if parsed.path in {"/api/bars", "/api/kline/bars"}:
                self._handle_kline_bars(params)
                return
```

- [ ] **Step 3: Document LAN workflow**

Add a short section to `docs/market-data-operations.md`:

````markdown
## Remote LAN Data Source API

Start the server that owns cached bars and crawl tasks:

```bash
uv run backtest data-source serve \
  --host 0.0.0.0 \
  --port 8768
```

From another machine, point the workbench K-line viewer at that server:

```bash
uv run backtest chart serve-workbench \
  --data-api-base-url http://SERVER_IP:8768 \
  --host 127.0.0.1 \
  --port 8767
```

Probe the remote API:

```bash
curl http://SERVER_IP:8768/api/health
curl http://SERVER_IP:8768/api/kline/manifest
```
````

- [ ] **Step 4: Run focused regression tests**

Run:

```bash
uv run pytest tests/charts/test_kline_cli.py tests/charts/test_kline_viewer.py tests/charts/test_workbench_server.py tests/test_cli_commands.py::test_chart_serve_workbench_cli_starts_combined_server -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backtest/charts/kline_server.py backtest/charts/workbench_server.py docs/market-data-operations.md
git commit -m "docs: describe remote data source workflow"
```

## Task 9: Final Verification

**Files:**
- No new files unless tests expose a defect.

- [ ] **Step 1: Run data-source and chart regression tests**

Run:

```bash
uv run pytest tests/data_source tests/charts/test_kline_service.py tests/charts/test_kline_viewer.py tests/charts/test_workbench_server.py tests/test_cli_commands.py -q
```

Expected: PASS.

- [ ] **Step 2: Run CLI help checks**

Run:

```bash
uv run backtest data-source serve --help
uv run backtest chart serve-workbench --help
```

Expected: both commands exit 0 and show `--host`, `--port`, and the new data-source options.

- [ ] **Step 3: Manual LAN-style local smoke test**

Run the data-source API on a free local port:

```bash
uv run backtest data-source serve \
  --host 127.0.0.1 \
  --port 8768
```

In another terminal, probe:

```bash
curl -sS http://127.0.0.1:8768/api/health
curl -sS http://127.0.0.1:8768/api/kline/manifest
curl -sS "http://127.0.0.1:8768/api/kline/bars?source_id=bitget&symbol=BTC%2FUSDT&frequency=1d&adjust=none&limit=2"
```

Expected: health returns `{"status":"ok","service":"backtest-data-source"}`, manifest includes configured sources, and bars returns `loaded_rows`.

- [ ] **Step 4: Manual workbench remote smoke test**

Run the workbench against the local data-source API:

```bash
uv run backtest chart serve-workbench \
  --data-api-base-url http://127.0.0.1:8768 \
  --host 127.0.0.1 \
  --port 8769
```

Open:

```text
http://127.0.0.1:8769/kline
```

Expected: K-line viewer loads data from port `8768` while the page is served from port `8769`.

- [ ] **Step 5: Commit final fixes if needed**

If Step 1 through Step 4 required code or doc changes, stage the known implementation paths and commit them:

```bash
git add backtest/data_source backtest/cli/app.py backtest/cli/data_source.py backtest/cli/chart.py backtest/charts/kline_server.py backtest/charts/kline_viewer.py backtest/charts/kline_viewer_template.html backtest/charts/workbench_server.py tests/data_source tests/charts/test_kline_viewer.py tests/charts/test_workbench_server.py tests/test_cli_commands.py docs/market-data-operations.md
git commit -m "fix: stabilize remote data source api"
```

If no files changed, do not create an empty commit.

## Self-Review Checklist

- Spec coverage: Tasks 1 through 5 cover data-source config, API facade, HTTP routes, job submission/status, tasks, inventory, retry, and CLI. Tasks 6 through 8 cover remote workbench K-line access and docs. Task 9 covers acceptance verification.
- Marker scan: no unresolved implementation markers or unresolved file names should remain in this plan.
- Type consistency: `DataSourceServerConfig`, `DataSourceSpec`, `DataSourceApi`, `DataSourceJobRegistry`, and `DataSourceJobSnapshot` are introduced before later tasks reference them.
