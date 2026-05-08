# Market Data Sync Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reusable, config-driven market data sync job runner for batch historical market data ingestion.

**Architecture:** A new `backtest.data.jobs` module owns job config validation, item expansion, retry orchestration, and summary artifact writing. The runner reuses the existing `DataSyncService`, `DataCatalog`, `ParquetBarStore`, and `CrawlTaskManager`; `backtest data sync-job` is only the CLI entrypoint.

**Tech Stack:** Python 3.11, Pydantic v2, Typer, pandas, PyYAML, pytest, existing Parquet/SQLite market data cache.

---

## Worktree Notes

Current branch: `feat/crypto-market-data`

The worktree may already contain unrelated local changes and generated data:

```text
backtest/charts/kline_viewer.py
tests/charts/test_kline_viewer.py
.superpowers/
data/crypto/
runs/
```

Do not stage or modify those unless the current task explicitly touches them. This plan only owns the market data sync job files listed below.

## File Structure

Create:

```text
backtest/data/jobs.py
tests/data/test_data_jobs.py
configs/data_jobs/crypto_bitget_core.yaml
```

Modify:

```text
backtest/cli/data.py
tests/test_cli_commands.py
docs/data-ingestion.md
docs/cli.md
docs/ai-handoff.md
```

Do not modify:

```text
backtest/data/service.py
backtest/data/ccxt_provider.py
backtest/data/store.py
```

The job runner should compose those existing modules instead of duplicating their responsibilities.

---

### Task 1: Add Job Config Loader

**Files:**
- Create: `backtest/data/jobs.py`
- Create: `tests/data/test_data_jobs.py`

- [ ] **Step 1: Write failing config tests**

Add this to `tests/data/test_data_jobs.py`:

```python
from datetime import date
from pathlib import Path

import pytest

from backtest.core.enums import AdjustMode, Frequency
from backtest.data.jobs import DataSyncJobConfig, load_data_sync_job_config


def _write_job_config(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "job.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_data_sync_job_config_normalizes_crypto_job(tmp_path: Path):
    job_path = _write_job_config(
        tmp_path,
        """
name: crypto-bitget-core
source: CCXT
exchange: Bitget
symbols:
  - btc/usdt
  - ETH/USDT
frequencies:
  - 1d
  - 4h
adjust: none
start_date: "2025-01-01"
end_date: "2025-01-31"
bars_root: data/crypto/bars
metadata: data/crypto/metadata.sqlite
output_dir: runs/crypto_market_data/bitget_core
retry:
  max_attempts: 5
  request_delay_seconds: 0.5
  failure_cooldown_seconds: 30
  continue_on_error: true
""",
    )

    config = load_data_sync_job_config(job_path)

    assert config.name == "crypto-bitget-core"
    assert config.source == "ccxt"
    assert config.exchange == "bitget"
    assert config.symbols == ["BTC/USDT", "ETH/USDT"]
    assert config.frequencies == [Frequency.DAILY, Frequency.HOUR_4]
    assert config.adjust == AdjustMode.NONE
    assert config.start_date == date(2025, 1, 1)
    assert config.end_date == date(2025, 1, 31)
    assert config.bars_root == Path("data/crypto/bars")
    assert config.metadata == Path("data/crypto/metadata.sqlite")
    assert config.output_dir == Path("runs/crypto_market_data/bitget_core")
    assert config.retry.max_attempts == 5
    assert config.retry.request_delay_seconds == 0.5
    assert config.retry.failure_cooldown_seconds == 30
    assert config.retry.continue_on_error is True
    assert config.catalog_source == "ccxt:bitget"


def test_data_sync_job_config_requires_exchange_for_ccxt():
    with pytest.raises(ValueError, match="exchange is required"):
        DataSyncJobConfig(
            name="bad-job",
            source="ccxt",
            symbols=["BTC/USDT"],
            frequencies=[Frequency.DAILY],
            adjust=AdjustMode.NONE,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 2),
        )


def test_data_sync_job_config_requires_none_adjust_for_ccxt():
    with pytest.raises(ValueError, match="adjust=none"):
        DataSyncJobConfig(
            name="bad-job",
            source="ccxt",
            exchange="bitget",
            symbols=["BTC/USDT"],
            frequencies=[Frequency.DAILY],
            adjust=AdjustMode.QFQ,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 2),
        )


def test_data_sync_job_config_rejects_empty_symbols():
    with pytest.raises(ValueError, match="symbols must not be empty"):
        DataSyncJobConfig(
            name="bad-job",
            source="akshare",
            symbols=[],
            frequencies=[Frequency.DAILY],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 2),
        )


def test_data_sync_job_config_rejects_inverted_date_range():
    with pytest.raises(ValueError, match="end_date must be on or after start_date"):
        DataSyncJobConfig(
            name="bad-job",
            source="akshare",
            symbols=["000001.SZ"],
            frequencies=[Frequency.DAILY],
            start_date=date(2025, 1, 3),
            end_date=date(2025, 1, 2),
        )
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/data/test_data_jobs.py -q
```

Expected: fail because `backtest.data.jobs` does not exist.

- [ ] **Step 3: Implement config models and loader**

Create `backtest/data/jobs.py` with:

```python
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from backtest.core.enums import AdjustMode, Frequency
from backtest.core.symbols import normalize_symbol


class RetryConfig(BaseModel):
    max_attempts: int = Field(default=3, ge=1)
    request_delay_seconds: float = Field(default=0.0, ge=0)
    failure_cooldown_seconds: float = Field(default=0.0, ge=0)
    continue_on_error: bool = True


class DataSyncJobConfig(BaseModel):
    name: str
    source: str
    exchange: str | None = None
    symbols: list[str]
    frequencies: list[Frequency]
    adjust: AdjustMode = AdjustMode.QFQ
    start_date: date
    end_date: date
    bars_root: Path = Path("data/bars")
    metadata: Path = Path("data/metadata.sqlite")
    output_dir: Path = Path("runs/data_jobs")
    retry: RetryConfig = Field(default_factory=RetryConfig)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be empty")
        return normalized

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("source must not be empty")
        return normalized

    @field_validator("exchange")
    @classmethod
    def normalize_exchange(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("symbols must not be empty")
        return [normalize_symbol(symbol) for symbol in value]

    @field_validator("frequencies")
    @classmethod
    def validate_frequencies(cls, value: list[Frequency]) -> list[Frequency]:
        if not value:
            raise ValueError("frequencies must not be empty")
        return value

    @model_validator(mode="after")
    def validate_job(self) -> "DataSyncJobConfig":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.source == "ccxt":
            if self.exchange is None:
                raise ValueError("exchange is required when source=ccxt")
            if self.adjust != AdjustMode.NONE:
                raise ValueError("source=ccxt requires adjust=none")
        return self

    @property
    def catalog_source(self) -> str:
        if self.source == "ccxt":
            return f"ccxt:{self.exchange}"
        return self.source


def load_data_sync_job_config(path: str | Path) -> DataSyncJobConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle)
    return DataSyncJobConfig.model_validate(data)
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
uv run pytest tests/data/test_data_jobs.py -q
```

Expected: all tests in `tests/data/test_data_jobs.py` pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add backtest/data/jobs.py tests/data/test_data_jobs.py
git commit -m "feat: add data sync job config"
```

---

### Task 2: Add Job Runner and Summary Artifacts

**Files:**
- Modify: `backtest/data/jobs.py`
- Modify: `tests/data/test_data_jobs.py`

- [ ] **Step 1: Write failing runner tests**

Append this to `tests/data/test_data_jobs.py`:

```python
from datetime import datetime

from backtest.core.contracts import CatalogRecord
from backtest.data.jobs import MarketDataJobRunner


class RecordingSyncService:
    def __init__(self, failures_before_success: int = 0) -> None:
        self.failures_before_success = failures_before_success
        self.calls: list[dict] = []

    def sync(self, **kwargs) -> None:
        self.calls.append(kwargs)
        if len(self.calls) <= self.failures_before_success:
            raise RuntimeError("temporary exchange error")


class AlwaysFailingSyncService:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def sync(self, **kwargs) -> None:
        self.calls.append(kwargs)
        raise RuntimeError("permanent exchange error")


class FakeCatalog:
    def coverage(self, symbol, frequency, adjust, source=None):
        return [
            CatalogRecord(
                symbol=symbol,
                frequency=frequency,
                adjust=adjust,
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 31),
                rows=7,
                source=source or "fixture",
                cache_path=Path("bars.parquet"),
                updated_at=datetime(2025, 1, 31, 12, 0, 0),
            )
        ]


def _job_config(tmp_path: Path, **overrides) -> DataSyncJobConfig:
    values = {
        "name": "runner-job",
        "source": "ccxt",
        "exchange": "bitget",
        "symbols": ["BTC/USDT", "ETH/USDT"],
        "frequencies": [Frequency.DAILY, Frequency.HOUR_4],
        "adjust": AdjustMode.NONE,
        "start_date": date(2025, 1, 1),
        "end_date": date(2025, 1, 31),
        "output_dir": tmp_path / "job-output",
    }
    values.update(overrides)
    return DataSyncJobConfig(**values)


def test_market_data_job_runner_expands_symbols_and_frequencies(tmp_path: Path):
    service = RecordingSyncService()
    runner = MarketDataJobRunner(
        service=service,
        catalog=FakeCatalog(),
        sleep=lambda seconds: None,
        now=lambda: datetime(2025, 2, 1, 0, 0, 0),
    )

    result = runner.run(_job_config(tmp_path))

    assert len(service.calls) == 4
    assert [
        (call["symbols"], call["frequency"], call["source"])
        for call in service.calls
    ] == [
        (["BTC/USDT"], Frequency.DAILY, "ccxt:bitget"),
        (["BTC/USDT"], Frequency.HOUR_4, "ccxt:bitget"),
        (["ETH/USDT"], Frequency.DAILY, "ccxt:bitget"),
        (["ETH/USDT"], Frequency.HOUR_4, "ccxt:bitget"),
    ]
    assert result.total_items == 4
    assert result.success_count == 4
    assert result.failed_count == 0
    assert result.total_rows == 28


def test_market_data_job_runner_retries_failed_item(tmp_path: Path):
    service = RecordingSyncService(failures_before_success=1)
    sleeps: list[float] = []
    config = _job_config(
        tmp_path,
        symbols=["BTC/USDT"],
        frequencies=[Frequency.DAILY],
        retry={
            "max_attempts": 2,
            "request_delay_seconds": 0,
            "failure_cooldown_seconds": 3,
            "continue_on_error": True,
        },
    )
    runner = MarketDataJobRunner(
        service=service,
        catalog=FakeCatalog(),
        sleep=sleeps.append,
        now=lambda: datetime(2025, 2, 1, 0, 0, 0),
    )

    result = runner.run(config)

    assert len(service.calls) == 2
    assert sleeps == [3]
    assert result.items[0].status == "success"
    assert result.items[0].attempts == 2
    assert result.items[0].error is None


def test_market_data_job_runner_continues_after_failed_item(tmp_path: Path):
    service = AlwaysFailingSyncService()
    config = _job_config(
        tmp_path,
        symbols=["BTC/USDT", "ETH/USDT"],
        frequencies=[Frequency.DAILY],
        retry={"max_attempts": 1, "continue_on_error": True},
    )
    runner = MarketDataJobRunner(
        service=service,
        catalog=FakeCatalog(),
        sleep=lambda seconds: None,
        now=lambda: datetime(2025, 2, 1, 0, 0, 0),
    )

    result = runner.run(config)

    assert len(service.calls) == 2
    assert result.total_items == 2
    assert result.success_count == 0
    assert result.failed_count == 2
    assert [item.error for item in result.items] == [
        "permanent exchange error",
        "permanent exchange error",
    ]


def test_market_data_job_runner_stops_when_continue_on_error_is_false(tmp_path: Path):
    service = AlwaysFailingSyncService()
    config = _job_config(
        tmp_path,
        symbols=["BTC/USDT", "ETH/USDT"],
        frequencies=[Frequency.DAILY],
        retry={"max_attempts": 1, "continue_on_error": False},
    )
    runner = MarketDataJobRunner(
        service=service,
        catalog=FakeCatalog(),
        sleep=lambda seconds: None,
        now=lambda: datetime(2025, 2, 1, 0, 0, 0),
    )

    with pytest.raises(RuntimeError, match="Data sync job runner-job failed"):
        runner.run(config)

    assert len(service.calls) == 1
    assert (tmp_path / "job-output" / "summary.csv").exists()
    assert (tmp_path / "job-output" / "summary.json").exists()


def test_market_data_job_runner_writes_summary_files(tmp_path: Path):
    service = RecordingSyncService()
    config = _job_config(
        tmp_path,
        symbols=["BTC/USDT"],
        frequencies=[Frequency.DAILY],
    )
    runner = MarketDataJobRunner(
        service=service,
        catalog=FakeCatalog(),
        sleep=lambda seconds: None,
        now=lambda: datetime(2025, 2, 1, 0, 0, 0),
    )

    result = runner.run(config)

    csv_text = (tmp_path / "job-output" / "summary.csv").read_text(encoding="utf-8")
    json_text = (tmp_path / "job-output" / "summary.json").read_text(encoding="utf-8")
    assert "BTC/USDT" in csv_text
    assert "success" in csv_text
    assert '"name": "runner-job"' in json_text
    assert result.items[0].rows == 7
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest tests/data/test_data_jobs.py -q
```

Expected: fail because `MarketDataJobRunner` and result models do not exist.

- [ ] **Step 3: Implement runner models**

Append these imports near the top of `backtest/data/jobs.py`:

```python
import json
import time
from collections.abc import Callable
from datetime import datetime

import pandas as pd

from backtest.data.catalog import DataCatalog
from backtest.data.service import DataSyncService
```

Append these classes to `backtest/data/jobs.py`:

```python
class JobItem(BaseModel):
    symbol: str
    frequency: Frequency
    adjust: AdjustMode
    start_date: date
    end_date: date
    source: str


class JobItemResult(BaseModel):
    job_name: str
    source: str
    exchange: str | None
    symbol: str
    frequency: Frequency
    adjust: AdjustMode
    start_date: date
    end_date: date
    status: str
    attempts: int
    rows: int = 0
    error: str | None = None
    started_at: datetime
    finished_at: datetime


class JobResult(BaseModel):
    name: str
    started_at: datetime
    finished_at: datetime | None = None
    items: list[JobItemResult] = Field(default_factory=list)

    @property
    def total_items(self) -> int:
        return len(self.items)

    @property
    def success_count(self) -> int:
        return sum(1 for item in self.items if item.status == "success")

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.items if item.status == "failed")

    @property
    def total_rows(self) -> int:
        return sum(item.rows for item in self.items)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([item.model_dump(mode="json") for item in self.items])

    def write(self, output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        self.to_frame().to_csv(output_dir / "summary.csv", index=False)
        payload = self.model_dump(mode="json")
        (output_dir / "summary.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


class MarketDataJobRunner:
    def __init__(
        self,
        service: DataSyncService,
        catalog: DataCatalog,
        *,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.service = service
        self.catalog = catalog
        self.sleep = sleep
        self.now = now

    def run(self, config: DataSyncJobConfig) -> JobResult:
        result = JobResult(name=config.name, started_at=self.now())
        try:
            for item in self._items(config):
                item_result = self._run_item(config, item)
                result.items.append(item_result)
                if item_result.status == "failed" and not config.retry.continue_on_error:
                    result.finished_at = self.now()
                    result.write(config.output_dir)
                    raise RuntimeError(
                        f"Data sync job {config.name} failed at {item.symbol} {item.frequency.value}: "
                        f"{item_result.error}"
                    )
        finally:
            result.finished_at = result.finished_at or self.now()
            result.write(config.output_dir)
        return result

    def _items(self, config: DataSyncJobConfig) -> list[JobItem]:
        return [
            JobItem(
                symbol=symbol,
                frequency=frequency,
                adjust=config.adjust,
                start_date=config.start_date,
                end_date=config.end_date,
                source=config.catalog_source,
            )
            for symbol in config.symbols
            for frequency in config.frequencies
        ]

    def _run_item(self, config: DataSyncJobConfig, item: JobItem) -> JobItemResult:
        started_at = self.now()
        last_error: str | None = None
        for attempt in range(1, config.retry.max_attempts + 1):
            if config.retry.request_delay_seconds:
                self.sleep(config.retry.request_delay_seconds)
            try:
                self.service.sync(
                    symbols=[item.symbol],
                    start_date=item.start_date,
                    end_date=item.end_date,
                    frequency=item.frequency,
                    adjust=item.adjust,
                    source=item.source,
                )
                return JobItemResult(
                    job_name=config.name,
                    source=item.source,
                    exchange=config.exchange,
                    symbol=item.symbol,
                    frequency=item.frequency,
                    adjust=item.adjust,
                    start_date=item.start_date,
                    end_date=item.end_date,
                    status="success",
                    attempts=attempt,
                    rows=self._covered_rows(item),
                    started_at=started_at,
                    finished_at=self.now(),
                )
            except Exception as exc:
                last_error = str(exc)
                if attempt < config.retry.max_attempts and config.retry.failure_cooldown_seconds:
                    self.sleep(config.retry.failure_cooldown_seconds)

        return JobItemResult(
            job_name=config.name,
            source=item.source,
            exchange=config.exchange,
            symbol=item.symbol,
            frequency=item.frequency,
            adjust=item.adjust,
            start_date=item.start_date,
            end_date=item.end_date,
            status="failed",
            attempts=config.retry.max_attempts,
            rows=0,
            error=last_error,
            started_at=started_at,
            finished_at=self.now(),
        )

    def _covered_rows(self, item: JobItem) -> int:
        rows = 0
        for record in self.catalog.coverage(
            item.symbol,
            item.frequency,
            item.adjust,
            source=item.source,
        ):
            if record.end_date < item.start_date or record.start_date > item.end_date:
                continue
            rows += record.rows
        return rows
```

- [ ] **Step 4: Run tests to verify pass**

Run:

```bash
uv run pytest tests/data/test_data_jobs.py -q
```

Expected: all tests in `tests/data/test_data_jobs.py` pass.

- [ ] **Step 5: Commit**

Run:

```bash
git add backtest/data/jobs.py tests/data/test_data_jobs.py
git commit -m "feat: add market data job runner"
```

---

### Task 3: Wire CLI Command

**Files:**
- Modify: `backtest/cli/data.py`
- Modify: `tests/test_cli_commands.py`

- [ ] **Step 1: Write failing CLI tests**

Append this helper and tests to `tests/test_cli_commands.py`:

```python
def _write_data_job_config(tmp_path: Path, *, failed_continue: bool = False) -> Path:
    job_path = tmp_path / "crypto-job.yaml"
    job_path.write_text(
        f"""
name: crypto-job
source: ccxt
exchange: bitget
symbols:
  - BTC/USDT
frequencies:
  - 1d
adjust: none
start_date: "2025-01-01"
end_date: "2025-01-31"
bars_root: {tmp_path / "bars"}
metadata: {tmp_path / "metadata.sqlite"}
output_dir: {tmp_path / "job-output"}
retry:
  max_attempts: 1
  continue_on_error: {str(failed_continue).lower()}
""",
        encoding="utf-8",
    )
    return job_path


def test_data_sync_job_cli_uses_ccxt_provider_and_runner(tmp_path: Path, monkeypatch):
    job_path = _write_data_job_config(tmp_path)
    captured = {}

    class FakeCCXTProvider:
        def __init__(self, exchange_id: str) -> None:
            self.exchange_id = exchange_id

    class NoopSyncService:
        def __init__(self, provider, store, catalog, tasks) -> None:
            captured["provider"] = provider
            captured["store_root"] = store.root
            captured["catalog"] = catalog

    class FakeRunner:
        def __init__(self, service, catalog) -> None:
            captured["runner_service"] = service
            captured["runner_catalog"] = catalog

        def run(self, config):
            captured["config"] = config

            class Result:
                total_items = 1
                success_count = 1
                failed_count = 0
                total_rows = 7

            return Result()

    monkeypatch.setattr(data_cli, "CCXTOHLCVProvider", FakeCCXTProvider)
    monkeypatch.setattr(data_cli, "DataSyncService", NoopSyncService)
    monkeypatch.setattr(data_cli, "MarketDataJobRunner", FakeRunner)

    result = CliRunner().invoke(app, ["data", "sync-job", "--job", str(job_path)])

    assert result.exit_code == 0
    assert "Data job crypto-job complete" in result.output
    assert "success=1 failed=0 rows=7" in result.output
    assert captured["provider"].exchange_id == "bitget"
    assert captured["store_root"] == tmp_path / "bars"
    assert captured["config"].catalog_source == "ccxt:bitget"


def test_data_sync_job_cli_returns_nonzero_when_result_has_failures(
    tmp_path: Path, monkeypatch
):
    job_path = _write_data_job_config(tmp_path, failed_continue=True)

    class FakeRunner:
        def __init__(self, service, catalog) -> None:
            pass

        def run(self, config):
            class Result:
                total_items = 1
                success_count = 0
                failed_count = 1
                total_rows = 0

            return Result()

    monkeypatch.setattr(data_cli, "MarketDataJobRunner", FakeRunner)

    result = CliRunner().invoke(app, ["data", "sync-job", "--job", str(job_path)])

    assert result.exit_code == 1
    assert "failed=1" in result.output
```

- [ ] **Step 2: Run CLI tests to verify failure**

Run:

```bash
uv run pytest tests/test_cli_commands.py -q
```

Expected: fail because `sync-job` command is not registered.

- [ ] **Step 3: Implement CLI imports and provider helper**

Modify imports in `backtest/cli/data.py`:

```python
from backtest.data.jobs import MarketDataJobRunner, load_data_sync_job_config
```

Add helper functions below `_catalog_source`:

```python
def _provider_for_source(source: str, exchange: str | None):
    if source == "akshare":
        return AkShareProvider()
    if source == "ccxt":
        if not exchange:
            raise ValueError("exchange is required when source=ccxt")
        return CCXTOHLCVProvider(exchange_id=exchange)
    raise ValueError(f"Unsupported data source: {source}")
```

- [ ] **Step 4: Implement CLI command**

Add this command to `backtest/cli/data.py` after `sync_data`:

```python
@app.command("sync-job")
def sync_job(
    job_path: Path = typer.Option(
        ...,
        "--job",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Path to market data sync job YAML",
    ),
) -> None:
    """Run a batch market data sync job."""
    try:
        config = load_data_sync_job_config(job_path)
        metadata = _metadata_store(config.metadata)
        catalog = DataCatalog(metadata)
        service = DataSyncService(
            provider=_provider_for_source(config.source, config.exchange),
            store=ParquetBarStore(config.bars_root),
            catalog=catalog,
            tasks=CrawlTaskManager(metadata),
        )
        result = MarketDataJobRunner(service=service, catalog=catalog).run(config)
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"Data job {config.name} complete: total={result.total_items} "
        f"success={result.success_count} failed={result.failed_count} rows={result.total_rows}"
    )
    typer.echo(f"Summary written to {config.output_dir / 'summary.csv'}")
    if result.failed_count:
        raise typer.Exit(code=1)
```

- [ ] **Step 5: Run CLI tests**

Run:

```bash
uv run pytest tests/test_cli_commands.py -q
```

Expected: all CLI tests pass.

- [ ] **Step 6: Run focused data tests**

Run:

```bash
uv run pytest tests/data/test_data_jobs.py tests/test_cli_commands.py -q
```

Expected: all focused tests pass.

- [ ] **Step 7: Commit**

Run:

```bash
git add backtest/cli/data.py tests/test_cli_commands.py
git commit -m "feat: add data sync job cli"
```

---

### Task 4: Add Example Job Config

**Files:**
- Create: `configs/data_jobs/crypto_bitget_core.yaml`

- [ ] **Step 1: Create example config**

Create `configs/data_jobs/crypto_bitget_core.yaml`:

```yaml
name: crypto-bitget-core
source: ccxt
exchange: bitget

symbols:
  - BTC/USDT
  - ETH/USDT
  - SOL/USDT
  - BNB/USDT

frequencies:
  - 1d
  - 4h
  - 60m
  - 30m
  - 15m
  - 5m
  - 1m

adjust: none
start_date: "2023-05-08"
end_date: "2026-05-08"

bars_root: data/crypto/bars
metadata: data/crypto/metadata.sqlite
output_dir: runs/crypto_market_data/bitget_core

retry:
  max_attempts: 5
  request_delay_seconds: 0.5
  failure_cooldown_seconds: 30
  continue_on_error: true
```

- [ ] **Step 2: Verify config parses**

Run:

```bash
uv run python - <<'PY'
from backtest.data.jobs import load_data_sync_job_config

config = load_data_sync_job_config("configs/data_jobs/crypto_bitget_core.yaml")
assert config.name == "crypto-bitget-core"
assert config.catalog_source == "ccxt:bitget"
assert len(config.symbols) == 4
assert len(config.frequencies) == 7
print(config)
PY
```

Expected: command exits 0 and prints the parsed config.

- [ ] **Step 3: Commit**

Run:

```bash
git add configs/data_jobs/crypto_bitget_core.yaml
git commit -m "chore: add crypto data sync job config"
```

---

### Task 5: Update Documentation and AI Handoff

**Files:**
- Modify: `docs/data-ingestion.md`
- Modify: `docs/cli.md`
- Modify: `docs/ai-handoff.md`

- [ ] **Step 1: Update data ingestion docs**

Add this section to `docs/data-ingestion.md` after the existing sync behavior section:

````markdown
## Market Data Sync Jobs

`backtest data sync` runs one backtest config's single `data.frequency`.
For recurring data production, use a market data sync job:

```bash
backtest data sync-job --job configs/data_jobs/crypto_bitget_core.yaml
```

A data job expands `symbols x frequencies`, reuses `DataSyncService` for each
item, and writes run artifacts to the configured `output_dir`:

```text
summary.csv
summary.json
```

The first tracked job example is `configs/data_jobs/crypto_bitget_core.yaml`.
It syncs Bitget spot OHLCV for `BTC/USDT`, `ETH/USDT`, `SOL/USDT`, and
`BNB/USDT` across `1d`, `4h`, `60m`, `30m`, `15m`, `5m`, and `1m`.

The CLI is designed for external schedulers. A cron or launchd task can call the
same command repeatedly; source-aware catalog coverage prevents already cached
ranges from being fetched again.
```
````

- [ ] **Step 2: Update CLI docs**

Add this to `docs/cli.md` in the data command area:

````markdown
### Batch Market Data Job

Run a configured batch data sync job:

```bash
backtest data sync-job --job configs/data_jobs/crypto_bitget_core.yaml
```

The command prints a short summary and writes detailed artifacts:

```text
runs/crypto_market_data/bitget_core/summary.csv
runs/crypto_market_data/bitget_core/summary.json
```

If any item fails, the command exits with code `1` after writing the summary.
With `retry.continue_on_error: true`, remaining items still run before the final
non-zero exit.
```
````

- [ ] **Step 3: Update AI handoff**

Add these bullets to `docs/ai-handoff.md` in the current branch capabilities and data sections:

```markdown
- Market data sync jobs are being added so batch data pulls are first-class project code rather than one-off terminal scripts.
- The planned entrypoint is `backtest data sync-job --job configs/data_jobs/crypto_bitget_core.yaml`.
- Data jobs reuse `DataSyncService`; do not duplicate parquet writing or catalog coverage logic in ad hoc scripts.
- Generated data under `data/crypto/` and run artifacts under `runs/crypto_market_data/` are local outputs and should not be staged unless the user explicitly asks.
```

- [ ] **Step 4: Run markdown and grep checks**

Run:

```bash
rg -n "sync-job|Market Data Sync Jobs|crypto_bitget_core" docs/data-ingestion.md docs/cli.md docs/ai-handoff.md
git diff --check -- docs/data-ingestion.md docs/cli.md docs/ai-handoff.md
```

Expected: `rg` shows the new references and `git diff --check` exits 0.

- [ ] **Step 5: Commit**

Run:

```bash
git add docs/data-ingestion.md docs/cli.md docs/ai-handoff.md
git commit -m "docs: document market data sync jobs"
```

---

### Task 6: Final Verification

**Files:**
- No new edits expected.

- [ ] **Step 1: Run focused test suite**

Run:

```bash
uv run pytest tests/data/test_data_jobs.py tests/test_cli_commands.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run full test suite**

Run:

```bash
uv run pytest -q
```

Expected: full suite passes. If unrelated K-line viewer worktree changes cause failures, record the failing test names and confirm whether those files belong to a separate in-progress change before editing them.

- [ ] **Step 3: Verify example job config loads**

Run:

```bash
uv run python - <<'PY'
from backtest.data.jobs import load_data_sync_job_config

config = load_data_sync_job_config("configs/data_jobs/crypto_bitget_core.yaml")
print(config.name, config.catalog_source, len(config.symbols), len(config.frequencies))
PY
```

Expected output includes:

```text
crypto-bitget-core ccxt:bitget 4 7
```

- [ ] **Step 4: Inspect git status**

Run:

```bash
git status --short --branch
```

Expected: implementation files are committed. Existing unrelated local changes or generated data may still appear and should remain unstaged.

- [ ] **Step 5: Summarize result**

Report:

```text
Implemented market data sync jobs.
Added config-driven job loading, retrying runner, sync-job CLI, Bitget crypto example, and docs.
Focused tests: pass.
Full tests: pass or list unrelated blockers.
```
