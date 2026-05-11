# A Share Backtest MVP Implementation Plan

> Historical note: this 2026-05-03 plan is the original A-share MVP plan. Its
> `config -> signal loading -> broker execution` flow is the legacy path. The
> current target architecture is documented in the 2026-05-10 strategy-planning
> and runtime dual-backend specs.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first working A share backtesting MVP as a Python package plus CLI, with pluggable data ingestion, Parquet cache, SQLite data catalog/task tracking, normalized signals, A share execution constraints, extensible metrics, reports, and durable docs.

**Architecture:** Implement one vertical research workflow: config -> data sync/catalog -> signal loading -> broker execution -> metrics -> report output. Keep extension points explicit through focused interfaces (`DataProvider`, `BarStore`, `SignalProvider`, `ExecutionModel`, `Metric`, `ReportWriter`) while shipping one concrete implementation for each MVP path.

**Tech Stack:** Python 3.11+, pandas, pyarrow, SQLite stdlib, Pydantic v2, Typer, Rich, Plotly, Jinja2, pytest, AkShare.

---

## Source Notes

- Design spec: `docs/superpowers/specs/2026-05-03-a-share-backtest-design.zh.md`
- Official AkShare stock data docs consulted during planning: `https://akshare.akfamily.xyz/data/stock/stock.html`
- The AkShare daily A share adapter should call `akshare.stock_zh_a_hist` for daily bars and normalize returned Chinese column names into the internal `BarFrame` contract.

## Scope Check

The design contains several modules, but they are not independent products. They form one local backtesting pipeline, so this is one implementation plan with incremental, testable tasks. Each task either establishes a contract, implements one module behind that contract, or connects the pipeline end to end.

## File Structure Map

Create this structure:

```text
backtest/
  __init__.py
  cli/
    __init__.py
    app.py
    data.py
    run.py
    validate.py
  config/
    __init__.py
    loader.py
    models.py
  core/
    __init__.py
    contracts.py
    enums.py
    frames.py
    symbols.py
  data/
    __init__.py
    akshare_provider.py
    catalog.py
    coverage.py
    metadata.py
    provider.py
    service.py
    store.py
    tasks.py
  signals/
    __init__.py
    context.py
    providers.py
    validators.py
  broker/
    __init__.py
    account.py
    costs.py
    engine.py
    execution.py
    slippage.py
  metrics/
    __init__.py
    builtin.py
    context.py
    registry.py
    results.py
  reports/
    __init__.py
    html.py
    manifest.py
    writer.py
  engine.py
```

Create tests in:

```text
tests/
  fixtures/
  test_smoke.py
  config/
  core/
  data/
  signals/
  broker/
  metrics/
  reports/
  test_engine_e2e.py
```

Documentation deliverables created near the end:

```text
README.md
docs/architecture.md
docs/data-ingestion.md
docs/data-contracts.md
docs/signal-integration.md
docs/metrics-extension.md
docs/reports.md
docs/cli.md
docs/ai-handoff.md
```

## Task 1: Project Scaffold and CLI Smoke Test

**Files:**

- Create: `pyproject.toml`
- Create: `backtest/__init__.py`
- Create: `backtest/cli/__init__.py`
- Create: `backtest/cli/app.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing smoke test**

Create `tests/test_smoke.py`:

```python
from typer.testing import CliRunner

from backtest.cli.app import app


def test_package_imports_version():
    import backtest

    assert isinstance(backtest.__version__, str)
    assert backtest.__version__


def test_cli_help_renders():
    runner = CliRunner()

    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "A Share backtest research CLI" in result.output
```

- [ ] **Step 2: Run the smoke test and confirm it fails**

Run:

```bash
pytest tests/test_smoke.py -v
```

Expected: FAIL because `backtest` package or `backtest.cli.app` does not exist.

- [ ] **Step 3: Add package metadata and dependencies**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "a-share-backtest"
version = "0.1.0"
description = "Local research-first A share backtesting system"
requires-python = ">=3.11"
dependencies = [
  "akshare>=1.18",
  "jinja2>=3.1",
  "pandas>=2.2",
  "plotly>=5.22",
  "pyarrow>=15",
  "pydantic>=2.7",
  "rich>=13.7",
  "typer>=0.12",
  "PyYAML>=6.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.2",
]

[project.scripts]
backtest = "backtest.cli.app:main"

[tool.setuptools.packages.find]
include = ["backtest*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 4: Add minimal package and CLI app**

Create `backtest/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `backtest/cli/__init__.py`:

```python
from backtest.cli.app import app, main

__all__ = ["app", "main"]
```

Create `backtest/cli/app.py`:

```python
import typer

app = typer.Typer(help="A Share backtest research CLI")


@app.callback()
def root() -> None:
    """Run data ingestion, backtests, validation, and reports."""


def main() -> None:
    app()
```

- [ ] **Step 5: Run the smoke test and confirm it passes**

Run:

```bash
pytest tests/test_smoke.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit scaffold**

Run:

```bash
git add pyproject.toml backtest tests/test_smoke.py
git commit -m "chore: scaffold backtest package"
```

Expected: commit succeeds.

## Task 2: Core Contracts, Enums, Symbols, and Frame Validation

**Files:**

- Create: `backtest/core/__init__.py`
- Create: `backtest/core/enums.py`
- Create: `backtest/core/symbols.py`
- Create: `backtest/core/contracts.py`
- Create: `backtest/core/frames.py`
- Create: `tests/core/test_symbols.py`
- Create: `tests/core/test_frames.py`

- [ ] **Step 1: Write symbol normalization tests**

Create `tests/core/test_symbols.py`:

```python
import pytest

from backtest.core.symbols import normalize_symbol


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("000001", "000001.SZ"),
        ("sz000001", "000001.SZ"),
        ("000001.sz", "000001.SZ"),
        ("600519", "600519.SH"),
        ("sh600519", "600519.SH"),
        ("600519.SH", "600519.SH"),
    ],
)
def test_normalize_symbol_accepts_common_a_share_forms(raw, expected):
    assert normalize_symbol(raw) == expected


def test_normalize_symbol_rejects_invalid_code():
    with pytest.raises(ValueError, match="Unsupported A share symbol"):
        normalize_symbol("ABC123")
```

- [ ] **Step 2: Write BarFrame and SignalFrame validation tests**

Create `tests/core/test_frames.py`:

```python
import pandas as pd
import pytest

from backtest.core.frames import validate_bar_frame, validate_signal_frame


def test_validate_bar_frame_normalizes_columns_and_symbols():
    raw = pd.DataFrame(
        {
            "date": ["2025-01-02"],
            "symbol": ["000001"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.5],
            "close": [10.5],
            "volume": [1000],
            "amount": [10500.0],
            "frequency": ["1d"],
            "adjust": ["qfq"],
        }
    )

    result = validate_bar_frame(raw)

    assert result.loc[0, "symbol"] == "000001.SZ"
    assert str(result.loc[0, "date"].date()) == "2025-01-02"


def test_validate_signal_frame_rejects_weight_sum_above_one():
    raw = pd.DataFrame(
        {
            "date": ["2025-01-02", "2025-01-02"],
            "symbol": ["000001.SZ", "600519.SH"],
            "target_weight": [0.70, 0.40],
        }
    )

    with pytest.raises(ValueError, match="target weight sum"):
        validate_signal_frame(raw, stock_pool=["000001.SZ", "600519.SH"])


def test_validate_signal_frame_rejects_symbol_outside_pool():
    raw = pd.DataFrame(
        {
            "date": ["2025-01-02"],
            "symbol": ["600519.SH"],
            "target_weight": [0.20],
        }
    )

    with pytest.raises(ValueError, match="outside stock pool"):
        validate_signal_frame(raw, stock_pool=["000001.SZ"])
```

- [ ] **Step 3: Run core tests and confirm they fail**

Run:

```bash
pytest tests/core -v
```

Expected: FAIL because core modules do not exist.

- [ ] **Step 4: Implement enums and symbol normalization**

Create `backtest/core/enums.py`:

```python
from enum import StrEnum


class Frequency(StrEnum):
    DAILY = "1d"
    MIN_1 = "1m"
    MIN_5 = "5m"
    MIN_15 = "15m"
    MIN_30 = "30m"
    MIN_60 = "60m"


class AdjustMode(StrEnum):
    NONE = "none"
    QFQ = "qfq"
    HFQ = "hfq"


class ExecutionTiming(StrEnum):
    NEXT_OPEN = "next_open"
    SAME_CLOSE = "same_close"
    NEXT_CLOSE = "next_close"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(StrEnum):
    FILLED = "filled"
    REJECTED = "rejected"
    ADJUSTED = "adjusted"


class MetricResultKind(StrEnum):
    SCALAR = "scalar"
    SERIES = "series"
    TABLE = "table"
```

Create `backtest/core/symbols.py`:

```python
import re


def normalize_symbol(raw: str) -> str:
    value = raw.strip().upper()
    value = value.replace("_", ".")

    if re.fullmatch(r"\d{6}\.(SZ|SH)", value):
        return value

    if re.fullmatch(r"(SZ|SH)\d{6}", value):
        return f"{value[2:]}.{value[:2]}"

    if re.fullmatch(r"\d{6}", value):
        suffix = "SH" if value.startswith(("5", "6", "9")) else "SZ"
        return f"{value}.{suffix}"

    raise ValueError(f"Unsupported A share symbol: {raw}")


def akshare_symbol(symbol: str) -> str:
    return normalize_symbol(symbol).split(".")[0]
```

Create `backtest/core/__init__.py`:

```python
from backtest.core.symbols import akshare_symbol, normalize_symbol

__all__ = ["akshare_symbol", "normalize_symbol"]
```

- [ ] **Step 5: Implement contracts and frame validators**

Create `backtest/core/contracts.py`:

```python
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backtest.core.enums import AdjustMode, Frequency, MetricResultKind, OrderSide, OrderStatus


class BarRequest(BaseModel):
    symbols: list[str]
    start_date: date
    end_date: date
    frequency: Frequency = Frequency.DAILY
    adjust: AdjustMode = AdjustMode.QFQ
    source: str = "akshare"


class CatalogRecord(BaseModel):
    symbol: str
    frequency: Frequency
    adjust: AdjustMode
    start_date: date
    end_date: date
    rows: int
    source: str
    cache_path: Path
    updated_at: datetime
    quality_status: str = "ok"


class CrawlTaskRecord(BaseModel):
    task_id: int | None = None
    symbol: str
    frequency: Frequency
    adjust: AdjustMode
    start_date: date
    end_date: date
    source: str
    status: str = "pending"
    attempts: int = 0
    last_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class OrderRecord(BaseModel):
    date: date
    symbol: str
    side: OrderSide
    requested_shares: int
    filled_shares: int
    price: float
    commission: float = 0.0
    tax: float = 0.0
    slippage_cost: float = 0.0
    status: OrderStatus
    reason: str = ""


class MetricResult(BaseModel):
    name: str
    kind: MetricResultKind
    value: Any
```

Create `backtest/core/frames.py`:

```python
from collections.abc import Sequence

import pandas as pd

from backtest.core.enums import AdjustMode, Frequency
from backtest.core.symbols import normalize_symbol

BAR_COLUMNS = ["date", "symbol", "open", "high", "low", "close", "volume", "amount", "frequency", "adjust"]
SIGNAL_COLUMNS = ["date", "symbol", "target_weight"]


def validate_bar_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = set(BAR_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"BarFrame missing columns: {sorted(missing)}")

    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"])
    result["symbol"] = result["symbol"].map(normalize_symbol)
    result["frequency"] = result["frequency"].map(lambda value: Frequency(value).value)
    result["adjust"] = result["adjust"].map(lambda value: AdjustMode(value).value)

    price_cols = ["open", "high", "low", "close"]
    for col in price_cols:
        result[col] = pd.to_numeric(result[col], errors="raise")
    result["volume"] = pd.to_numeric(result["volume"], errors="raise")
    result["amount"] = pd.to_numeric(result["amount"], errors="raise")

    if (result["high"] < result["low"]).any():
        raise ValueError("BarFrame contains high lower than low")
    if (result[price_cols] < 0).any().any():
        raise ValueError("BarFrame contains negative prices")

    return result.sort_values(["symbol", "date"]).reset_index(drop=True)


def validate_signal_frame(frame: pd.DataFrame, stock_pool: Sequence[str] | None = None) -> pd.DataFrame:
    missing = set(SIGNAL_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"SignalFrame missing columns: {sorted(missing)}")

    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"])
    result["symbol"] = result["symbol"].map(normalize_symbol)
    result["target_weight"] = pd.to_numeric(result["target_weight"], errors="raise")

    if result.duplicated(["date", "symbol"]).any():
        raise ValueError("SignalFrame contains duplicate date + symbol rows")
    if ((result["target_weight"] < 0) | (result["target_weight"] > 1)).any():
        raise ValueError("SignalFrame target_weight must be between 0 and 1")

    daily_sum = result.groupby("date")["target_weight"].sum()
    if (daily_sum > 1.0 + 1e-9).any():
        raise ValueError("SignalFrame target weight sum exceeds 1.0 on at least one date")

    if stock_pool is not None:
        normalized_pool = {normalize_symbol(symbol) for symbol in stock_pool}
        outside = sorted(set(result["symbol"]) - normalized_pool)
        if outside:
            raise ValueError(f"SignalFrame contains symbols outside stock pool: {outside}")

    return result.sort_values(["date", "symbol"]).reset_index(drop=True)
```

- [ ] **Step 6: Run core tests and confirm they pass**

Run:

```bash
pytest tests/core -v
```

Expected: PASS.

- [ ] **Step 7: Commit core contracts**

Run:

```bash
git add backtest/core tests/core
git commit -m "feat: add core data contracts"
```

Expected: commit succeeds.

## Task 3: YAML Config Models and Loader

**Files:**

- Create: `backtest/config/__init__.py`
- Create: `backtest/config/models.py`
- Create: `backtest/config/loader.py`
- Create: `tests/config/test_config_loader.py`

- [ ] **Step 1: Write config loader tests**

Create `tests/config/test_config_loader.py`:

```python
from datetime import date
from pathlib import Path

import pytest

from backtest.config.loader import load_config


def test_load_config_normalizes_stock_pool(tmp_path: Path):
    config_path = tmp_path / "demo.yaml"
    config_path.write_text(
        """
project:
  name: demo
data:
  source: akshare
  frequency: 1d
  adjust: qfq
  start_date: "2025-01-01"
  end_date: "2025-01-31"
  stock_pool:
    symbols:
      - "000001"
signals:
  type: file
  path: signals/demo.csv
execution:
  timing: next_open
  initial_cash: 1000000
  commission_rate: 0.0003
  min_commission: 5
  stamp_tax_rate: 0.0005
  slippage_rate: 0.0005
  board_lot_size: 100
metrics:
  builtin:
    - total_return
report:
  output_dir: runs
  html: true
  charts: true
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.project.name == "demo"
    assert config.data.stock_pool.symbols == ["000001.SZ"]


def test_load_config_rejects_end_before_start(tmp_path: Path):
    config_path = tmp_path / "bad.yaml"
    config_path.write_text(
        """
project:
  name: bad
data:
  source: akshare
  frequency: 1d
  adjust: qfq
  start_date: "2025-02-01"
  end_date: "2025-01-31"
  stock_pool:
    symbols:
      - "000001.SZ"
signals:
  type: file
  path: signals/demo.csv
execution:
  timing: next_open
  initial_cash: 1000000
  commission_rate: 0.0003
  min_commission: 5
  stamp_tax_rate: 0.0005
  slippage_rate: 0.0005
  board_lot_size: 100
metrics:
  builtin:
    - total_return
report:
  output_dir: runs
  html: true
  charts: true
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="end_date must be on or after start_date"):
        load_config(config_path)
```

- [ ] **Step 2: Run config tests and confirm they fail**

Run:

```bash
pytest tests/config -v
```

Expected: FAIL because config modules do not exist.

- [ ] **Step 3: Implement Pydantic config models**

Create `backtest/config/models.py`:

```python
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backtest.core.enums import AdjustMode, ExecutionTiming, Frequency
from backtest.core.symbols import normalize_symbol


class ProjectConfig(BaseModel):
    name: str


class StockPoolConfig(BaseModel):
    symbols: list[str]

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("stock_pool.symbols must not be empty")
        return [normalize_symbol(symbol) for symbol in value]


class DataConfig(BaseModel):
    source: str = "akshare"
    frequency: Frequency = Frequency.DAILY
    adjust: AdjustMode = AdjustMode.QFQ
    start_date: date
    end_date: date
    stock_pool: StockPoolConfig

    @model_validator(mode="after")
    def validate_dates(self) -> "DataConfig":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class SignalsConfig(BaseModel):
    type: Literal["file", "python"]
    path: Path
    function: str = "generate_signals"


class ExecutionConfig(BaseModel):
    timing: ExecutionTiming = ExecutionTiming.NEXT_OPEN
    initial_cash: float = Field(gt=0)
    commission_rate: float = Field(ge=0)
    min_commission: float = Field(ge=0)
    stamp_tax_rate: float = Field(ge=0)
    slippage_rate: float = Field(ge=0)
    board_lot_size: int = Field(default=100, gt=0)


class MetricsConfig(BaseModel):
    builtin: list[str] = Field(default_factory=list)
    custom: list[dict[str, str]] = Field(default_factory=list)


class ReportConfig(BaseModel):
    output_dir: Path = Path("runs")
    html: bool = True
    charts: bool = True


class BacktestConfig(BaseModel):
    project: ProjectConfig
    data: DataConfig
    signals: SignalsConfig
    execution: ExecutionConfig
    metrics: MetricsConfig
    report: ReportConfig
```

- [ ] **Step 4: Implement config loader**

Create `backtest/config/loader.py`:

```python
from pathlib import Path
from typing import Any

import yaml

from backtest.config.models import BacktestConfig


def load_config(path: str | Path) -> BacktestConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle)
    return BacktestConfig.model_validate(data)
```

Create `backtest/config/__init__.py`:

```python
from backtest.config.loader import load_config
from backtest.config.models import BacktestConfig

__all__ = ["BacktestConfig", "load_config"]
```

- [ ] **Step 5: Run config tests and confirm they pass**

Run:

```bash
pytest tests/config -v
```

Expected: PASS.

- [ ] **Step 6: Commit config models**

Run:

```bash
git add backtest/config tests/config
git commit -m "feat: add YAML config validation"
```

Expected: commit succeeds.

## Task 4: SQLite Metadata, DataCatalog, and CrawlTaskManager

**Files:**

- Create: `backtest/data/__init__.py`
- Create: `backtest/data/metadata.py`
- Create: `backtest/data/catalog.py`
- Create: `backtest/data/tasks.py`
- Create: `tests/data/test_catalog.py`
- Create: `tests/data/test_tasks.py`

- [ ] **Step 1: Write DataCatalog tests**

Create `tests/data/test_catalog.py`:

```python
from datetime import date
from pathlib import Path

from backtest.core.contracts import CatalogRecord
from backtest.core.enums import AdjustMode, Frequency
from backtest.data.catalog import DataCatalog
from backtest.data.metadata import MetadataStore


def test_catalog_records_coverage_and_missing_ranges(tmp_path: Path):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    catalog = DataCatalog(metadata)
    catalog.upsert(
        CatalogRecord(
            symbol="000001.SZ",
            frequency=Frequency.DAILY,
            adjust=AdjustMode.QFQ,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 10),
            rows=7,
            source="fixture",
            cache_path=tmp_path / "bars.parquet",
            updated_at=metadata.now(),
        )
    )

    records = catalog.inventory()
    missing = catalog.missing_ranges(
        symbols=["000001.SZ", "600519.SH"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 15),
        frequency=Frequency.DAILY,
        adjust=AdjustMode.QFQ,
    )

    assert len(records) == 1
    assert missing == [
        ("000001.SZ", date(2025, 1, 1), date(2025, 1, 1)),
        ("000001.SZ", date(2025, 1, 11), date(2025, 1, 15)),
        ("600519.SH", date(2025, 1, 1), date(2025, 1, 15)),
    ]
```

- [ ] **Step 2: Write CrawlTaskManager tests**

Create `tests/data/test_tasks.py`:

```python
from datetime import date
from pathlib import Path

from backtest.core.enums import AdjustMode, Frequency
from backtest.data.metadata import MetadataStore
from backtest.data.tasks import CrawlTaskManager


def test_task_manager_lifecycle_and_failed_retry_selection(tmp_path: Path):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    tasks = CrawlTaskManager(metadata)

    task_id = tasks.create_task(
        symbol="000001.SZ",
        frequency=Frequency.DAILY,
        adjust=AdjustMode.QFQ,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        source="fixture",
    )
    tasks.mark_running(task_id)
    tasks.mark_failed(task_id, "timeout")

    failed = tasks.failed_tasks()

    assert failed[0].task_id == task_id
    assert failed[0].status == "failed"
    assert failed[0].attempts == 1
    assert failed[0].last_error == "timeout"
```

- [ ] **Step 3: Run metadata tests and confirm they fail**

Run:

```bash
pytest tests/data/test_catalog.py tests/data/test_tasks.py -v
```

Expected: FAIL because metadata modules do not exist.

- [ ] **Step 4: Implement SQLite metadata store**

Create `backtest/data/metadata.py`:

```python
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class MetadataStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS catalog (
                    symbol TEXT NOT NULL,
                    frequency TEXT NOT NULL,
                    adjust TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    rows INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    cache_path TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    quality_status TEXT NOT NULL,
                    PRIMARY KEY (symbol, frequency, adjust, cache_path)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS crawl_tasks (
                    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    frequency TEXT NOT NULL,
                    adjust TEXT NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
                """
            )
```

- [ ] **Step 5: Implement DataCatalog**

Create `backtest/data/catalog.py`:

```python
from datetime import date, datetime
from pathlib import Path

from backtest.core.contracts import CatalogRecord
from backtest.core.enums import AdjustMode, Frequency
from backtest.data.metadata import MetadataStore


class DataCatalog:
    def __init__(self, metadata: MetadataStore) -> None:
        self.metadata = metadata

    def upsert(self, record: CatalogRecord) -> None:
        with self.metadata.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO catalog
                (symbol, frequency, adjust, start_date, end_date, rows, source, cache_path, updated_at, quality_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.symbol,
                    record.frequency.value,
                    record.adjust.value,
                    record.start_date.isoformat(),
                    record.end_date.isoformat(),
                    record.rows,
                    record.source,
                    str(record.cache_path),
                    record.updated_at.isoformat(),
                    record.quality_status,
                ),
            )

    def inventory(self) -> list[CatalogRecord]:
        with self.metadata.connect() as conn:
            rows = conn.execute("SELECT * FROM catalog ORDER BY symbol, start_date").fetchall()
        return [self._record_from_row(row) for row in rows]

    def coverage(self, symbol: str, frequency: Frequency, adjust: AdjustMode) -> list[CatalogRecord]:
        with self.metadata.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM catalog
                WHERE symbol = ? AND frequency = ? AND adjust = ?
                ORDER BY start_date
                """,
                (symbol, frequency.value, adjust.value),
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def missing_ranges(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        frequency: Frequency,
        adjust: AdjustMode,
    ) -> list[tuple[str, date, date]]:
        missing: list[tuple[str, date, date]] = []
        for symbol in symbols:
            ranges = [(record.start_date, record.end_date) for record in self.coverage(symbol, frequency, adjust)]
            if not ranges:
                missing.append((symbol, start_date, end_date))
                continue
            ranges.sort()
            cursor = start_date
            for covered_start, covered_end in ranges:
                if covered_end < cursor:
                    continue
                if covered_start > cursor:
                    missing.append((symbol, cursor, covered_start.fromordinal(covered_start.toordinal() - 1)))
                if covered_end >= cursor:
                    cursor = covered_end.fromordinal(covered_end.toordinal() + 1)
                if cursor > end_date:
                    break
            if cursor <= end_date:
                missing.append((symbol, cursor, end_date))
        return missing

    def _record_from_row(self, row) -> CatalogRecord:
        return CatalogRecord(
            symbol=row["symbol"],
            frequency=Frequency(row["frequency"]),
            adjust=AdjustMode(row["adjust"]),
            start_date=date.fromisoformat(row["start_date"]),
            end_date=date.fromisoformat(row["end_date"]),
            rows=row["rows"],
            source=row["source"],
            cache_path=Path(row["cache_path"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            quality_status=row["quality_status"],
        )
```

- [ ] **Step 6: Implement CrawlTaskManager**

Create `backtest/data/tasks.py`:

```python
from datetime import date, datetime

from backtest.core.contracts import CrawlTaskRecord
from backtest.core.enums import AdjustMode, Frequency
from backtest.data.metadata import MetadataStore


class CrawlTaskManager:
    def __init__(self, metadata: MetadataStore) -> None:
        self.metadata = metadata

    def create_task(
        self,
        symbol: str,
        frequency: Frequency,
        adjust: AdjustMode,
        start_date: date,
        end_date: date,
        source: str,
    ) -> int:
        now = self.metadata.now().isoformat()
        with self.metadata.connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO crawl_tasks
                (symbol, frequency, adjust, start_date, end_date, source, status, attempts, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)
                """,
                (symbol, frequency.value, adjust.value, start_date.isoformat(), end_date.isoformat(), source, now, now),
            )
            return int(cursor.lastrowid)

    def mark_running(self, task_id: int) -> None:
        now = self.metadata.now().isoformat()
        with self.metadata.connect() as conn:
            conn.execute(
                """
                UPDATE crawl_tasks
                SET status = 'running', attempts = attempts + 1, updated_at = ?, started_at = ?
                WHERE task_id = ?
                """,
                (now, now, task_id),
            )

    def mark_success(self, task_id: int) -> None:
        now = self.metadata.now().isoformat()
        with self.metadata.connect() as conn:
            conn.execute(
                """
                UPDATE crawl_tasks
                SET status = 'success', updated_at = ?, finished_at = ?, last_error = NULL
                WHERE task_id = ?
                """,
                (now, now, task_id),
            )

    def mark_failed(self, task_id: int, error: str) -> None:
        now = self.metadata.now().isoformat()
        with self.metadata.connect() as conn:
            conn.execute(
                """
                UPDATE crawl_tasks
                SET status = 'failed', updated_at = ?, finished_at = ?, last_error = ?
                WHERE task_id = ?
                """,
                (now, now, error, task_id),
            )

    def failed_tasks(self) -> list[CrawlTaskRecord]:
        with self.metadata.connect() as conn:
            rows = conn.execute("SELECT * FROM crawl_tasks WHERE status = 'failed' ORDER BY updated_at").fetchall()
        return [self._record_from_row(row) for row in rows]

    def list_tasks(self) -> list[CrawlTaskRecord]:
        with self.metadata.connect() as conn:
            rows = conn.execute("SELECT * FROM crawl_tasks ORDER BY created_at").fetchall()
        return [self._record_from_row(row) for row in rows]

    def _record_from_row(self, row) -> CrawlTaskRecord:
        parse_dt = lambda value: datetime.fromisoformat(value) if value else None
        return CrawlTaskRecord(
            task_id=row["task_id"],
            symbol=row["symbol"],
            frequency=Frequency(row["frequency"]),
            adjust=AdjustMode(row["adjust"]),
            start_date=date.fromisoformat(row["start_date"]),
            end_date=date.fromisoformat(row["end_date"]),
            source=row["source"],
            status=row["status"],
            attempts=row["attempts"],
            last_error=row["last_error"],
            created_at=parse_dt(row["created_at"]),
            updated_at=parse_dt(row["updated_at"]),
            started_at=parse_dt(row["started_at"]),
            finished_at=parse_dt(row["finished_at"]),
        )
```

Create `backtest/data/__init__.py`:

```python
from backtest.data.catalog import DataCatalog
from backtest.data.metadata import MetadataStore
from backtest.data.tasks import CrawlTaskManager

__all__ = ["CrawlTaskManager", "DataCatalog", "MetadataStore"]
```

- [ ] **Step 7: Run metadata tests and confirm they pass**

Run:

```bash
pytest tests/data/test_catalog.py tests/data/test_tasks.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit metadata layer**

Run:

```bash
git add backtest/data tests/data/test_catalog.py tests/data/test_tasks.py
git commit -m "feat: add data catalog and crawl tasks"
```

Expected: commit succeeds.

## Task 5: Parquet BarStore and Coverage Planning

**Files:**

- Create: `backtest/data/store.py`
- Create: `backtest/data/coverage.py`
- Create: `tests/data/test_store.py`
- Create: `tests/data/test_coverage.py`

- [ ] **Step 1: Write Parquet store tests**

Create `tests/data/test_store.py`:

```python
from pathlib import Path

import pandas as pd

from backtest.core.enums import AdjustMode, Frequency
from backtest.data.store import ParquetBarStore


def test_parquet_store_writes_partitioned_bars_and_reads_range(tmp_path: Path):
    store = ParquetBarStore(tmp_path / "bars")
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "symbol": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 10.5],
            "high": [11.0, 11.2],
            "low": [9.8, 10.1],
            "close": [10.5, 10.8],
            "volume": [1000, 1200],
            "amount": [10500.0, 12960.0],
            "frequency": ["1d", "1d"],
            "adjust": ["qfq", "qfq"],
        }
    )

    written = store.write_bars(bars)
    loaded = store.read_bars(
        symbols=["000001.SZ"],
        start_date=pd.Timestamp("2025-01-02").date(),
        end_date=pd.Timestamp("2025-01-03").date(),
        frequency=Frequency.DAILY,
        adjust=AdjustMode.QFQ,
    )

    assert written
    assert len(loaded) == 2
    assert loaded["close"].tolist() == [10.5, 10.8]
```

- [ ] **Step 2: Write coverage planner tests**

Create `tests/data/test_coverage.py`:

```python
from datetime import date

from backtest.data.coverage import split_missing_ranges_to_tasks


def test_split_missing_ranges_keeps_one_task_per_symbol_range():
    missing = [
        ("000001.SZ", date(2025, 1, 1), date(2025, 1, 5)),
        ("600519.SH", date(2025, 1, 1), date(2025, 1, 5)),
    ]

    tasks = split_missing_ranges_to_tasks(missing)

    assert tasks == missing
```

- [ ] **Step 3: Run store tests and confirm they fail**

Run:

```bash
pytest tests/data/test_store.py tests/data/test_coverage.py -v
```

Expected: FAIL because `ParquetBarStore` and coverage planner do not exist.

- [ ] **Step 4: Implement ParquetBarStore**

Create `backtest/data/store.py`:

```python
from datetime import date
from pathlib import Path

import pandas as pd

from backtest.core.enums import AdjustMode, Frequency
from backtest.core.frames import validate_bar_frame


class ParquetBarStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def partition_path(self, symbol: str, frequency: Frequency, adjust: AdjustMode, year: int) -> Path:
        return (
            self.root
            / f"frequency={frequency.value}"
            / f"adjust={adjust.value}"
            / f"symbol={symbol}"
            / f"year={year}"
            / "bars.parquet"
        )

    def write_bars(self, bars: pd.DataFrame) -> list[Path]:
        validated = validate_bar_frame(bars)
        written: list[Path] = []
        for (symbol, frequency, adjust, year), group in validated.groupby(
            ["symbol", "frequency", "adjust", validated["date"].dt.year]
        ):
            path = self.partition_path(symbol, Frequency(frequency), AdjustMode(adjust), int(year))
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                existing = pd.read_parquet(path)
                group = pd.concat([existing, group], ignore_index=True)
                group = group.drop_duplicates(["date", "symbol"], keep="last")
                group = group.sort_values(["symbol", "date"]).reset_index(drop=True)
            tmp_path = path.with_suffix(".tmp.parquet")
            group.to_parquet(tmp_path, index=False)
            tmp_path.replace(path)
            written.append(path)
        return written

    def read_bars(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        frequency: Frequency,
        adjust: AdjustMode,
    ) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for symbol in symbols:
            for year in range(start_date.year, end_date.year + 1):
                path = self.partition_path(symbol, frequency, adjust, year)
                if path.exists():
                    frames.append(pd.read_parquet(path))
        if not frames:
            return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "volume", "amount", "frequency", "adjust"])
        result = pd.concat(frames, ignore_index=True)
        result["date"] = pd.to_datetime(result["date"])
        mask = (
            result["symbol"].isin(symbols)
            & (result["date"] >= pd.Timestamp(start_date))
            & (result["date"] <= pd.Timestamp(end_date))
        )
        return result.loc[mask].sort_values(["symbol", "date"]).reset_index(drop=True)
```

- [ ] **Step 5: Implement coverage planner**

Create `backtest/data/coverage.py`:

```python
from datetime import date


def split_missing_ranges_to_tasks(
    missing_ranges: list[tuple[str, date, date]],
) -> list[tuple[str, date, date]]:
    return list(missing_ranges)
```

- [ ] **Step 6: Run store tests and confirm they pass**

Run:

```bash
pytest tests/data/test_store.py tests/data/test_coverage.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit BarStore**

Run:

```bash
git add backtest/data/store.py backtest/data/coverage.py tests/data/test_store.py tests/data/test_coverage.py
git commit -m "feat: add Parquet bar store"
```

Expected: commit succeeds.

## Task 6: DataProvider Interface, AkShare Adapter, and Data Sync Service

**Files:**

- Create: `backtest/data/provider.py`
- Create: `backtest/data/akshare_provider.py`
- Create: `backtest/data/service.py`
- Create: `tests/data/test_akshare_provider.py`
- Create: `tests/data/test_data_service.py`

- [ ] **Step 1: Write AkShare adapter normalization test**

Create `tests/data/test_akshare_provider.py`:

```python
from datetime import date

import pandas as pd

from backtest.core.contracts import BarRequest
from backtest.data.akshare_provider import AkShareProvider


def test_akshare_provider_normalizes_daily_columns(monkeypatch):
    calls = {}

    def fake_stock_zh_a_hist(symbol, period, start_date, end_date, adjust):
        calls.update(
            {
                "symbol": symbol,
                "period": period,
                "start_date": start_date,
                "end_date": end_date,
                "adjust": adjust,
            }
        )
        return pd.DataFrame(
            {
                "日期": ["2025-01-02"],
                "股票代码": ["000001"],
                "开盘": [10.0],
                "收盘": [10.5],
                "最高": [11.0],
                "最低": [9.8],
                "成交量": [1000],
                "成交额": [10500.0],
            }
        )

    import backtest.data.akshare_provider as module

    monkeypatch.setattr(module.ak, "stock_zh_a_hist", fake_stock_zh_a_hist)

    provider = AkShareProvider()
    result = provider.fetch_bars(
        BarRequest(
            symbols=["000001.SZ"],
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 2),
        )
    )

    assert calls == {
        "symbol": "000001",
        "period": "daily",
        "start_date": "20250102",
        "end_date": "20250102",
        "adjust": "qfq",
    }
    assert result.loc[0, "symbol"] == "000001.SZ"
    assert result.loc[0, "frequency"] == "1d"
    assert result.loc[0, "adjust"] == "qfq"
```

- [ ] **Step 2: Write data sync service test**

Create `tests/data/test_data_service.py`:

```python
from datetime import date
from pathlib import Path

import pandas as pd

from backtest.core.contracts import BarRequest
from backtest.data.catalog import DataCatalog
from backtest.data.metadata import MetadataStore
from backtest.data.service import DataSyncService
from backtest.data.store import ParquetBarStore
from backtest.data.tasks import CrawlTaskManager


class FakeProvider:
    def fetch_bars(self, request: BarRequest) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": [request.start_date],
                "symbol": [request.symbols[0]],
                "open": [10.0],
                "high": [11.0],
                "low": [9.8],
                "close": [10.5],
                "volume": [1000],
                "amount": [10500.0],
                "frequency": [request.frequency.value],
                "adjust": [request.adjust.value],
            }
        )


def test_data_sync_service_fetches_missing_range_and_updates_catalog(tmp_path: Path):
    metadata = MetadataStore(tmp_path / "metadata.sqlite")
    service = DataSyncService(
        provider=FakeProvider(),
        store=ParquetBarStore(tmp_path / "bars"),
        catalog=DataCatalog(metadata),
        tasks=CrawlTaskManager(metadata),
    )

    service.sync(
        symbols=["000001.SZ"],
        start_date=date(2025, 1, 2),
        end_date=date(2025, 1, 2),
    )

    assert len(service.catalog.inventory()) == 1
    assert service.tasks.list_tasks()[0].status == "success"
```

- [ ] **Step 3: Run data provider tests and confirm they fail**

Run:

```bash
pytest tests/data/test_akshare_provider.py tests/data/test_data_service.py -v
```

Expected: FAIL because provider and service modules do not exist.

- [ ] **Step 4: Implement DataProvider protocol**

Create `backtest/data/provider.py`:

```python
from typing import Protocol

import pandas as pd

from backtest.core.contracts import BarRequest


class DataProvider(Protocol):
    def fetch_bars(self, request: BarRequest) -> pd.DataFrame:
        raise NotImplementedError
```

- [ ] **Step 5: Implement AkShareProvider**

Create `backtest/data/akshare_provider.py`:

```python
import pandas as pd
import akshare as ak

from backtest.core.contracts import BarRequest
from backtest.core.enums import AdjustMode, Frequency
from backtest.core.frames import validate_bar_frame
from backtest.core.symbols import akshare_symbol, normalize_symbol


class AkShareProvider:
    def fetch_bars(self, request: BarRequest) -> pd.DataFrame:
        if request.frequency != Frequency.DAILY:
            raise ValueError("AkShareProvider MVP supports only daily bars")

        frames: list[pd.DataFrame] = []
        for symbol in request.symbols:
            normalized_symbol = normalize_symbol(symbol)
            raw = ak.stock_zh_a_hist(
                symbol=akshare_symbol(normalized_symbol),
                period="daily",
                start_date=request.start_date.strftime("%Y%m%d"),
                end_date=request.end_date.strftime("%Y%m%d"),
                adjust="" if request.adjust == AdjustMode.NONE else request.adjust.value,
            )
            if raw.empty:
                continue
            frame = raw.rename(
                columns={
                    "日期": "date",
                    "股票代码": "symbol",
                    "开盘": "open",
                    "收盘": "close",
                    "最高": "high",
                    "最低": "low",
                    "成交量": "volume",
                    "成交额": "amount",
                }
            )
            frame["symbol"] = normalized_symbol
            frame["frequency"] = request.frequency.value
            frame["adjust"] = request.adjust.value
            frames.append(frame[["date", "symbol", "open", "high", "low", "close", "volume", "amount", "frequency", "adjust"]])

        if not frames:
            return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "volume", "amount", "frequency", "adjust"])

        return validate_bar_frame(pd.concat(frames, ignore_index=True))
```

- [ ] **Step 6: Implement DataSyncService**

Create `backtest/data/service.py`:

```python
from datetime import date

from backtest.core.contracts import BarRequest, CatalogRecord
from backtest.core.enums import AdjustMode, Frequency
from backtest.core.symbols import normalize_symbol
from backtest.data.catalog import DataCatalog
from backtest.data.provider import DataProvider
from backtest.data.store import ParquetBarStore
from backtest.data.tasks import CrawlTaskManager


class DataSyncService:
    def __init__(
        self,
        provider: DataProvider,
        store: ParquetBarStore,
        catalog: DataCatalog,
        tasks: CrawlTaskManager,
    ) -> None:
        self.provider = provider
        self.store = store
        self.catalog = catalog
        self.tasks = tasks

    def sync(
        self,
        symbols: list[str],
        start_date: date,
        end_date: date,
        frequency: Frequency = Frequency.DAILY,
        adjust: AdjustMode = AdjustMode.QFQ,
        source: str = "akshare",
    ) -> None:
        normalized_symbols = [normalize_symbol(symbol) for symbol in symbols]
        missing = self.catalog.missing_ranges(normalized_symbols, start_date, end_date, frequency, adjust)
        for symbol, missing_start, missing_end in missing:
            task_id = self.tasks.create_task(symbol, frequency, adjust, missing_start, missing_end, source)
            self.tasks.mark_running(task_id)
            try:
                bars = self.provider.fetch_bars(
                    BarRequest(
                        symbols=[symbol],
                        start_date=missing_start,
                        end_date=missing_end,
                        frequency=frequency,
                        adjust=adjust,
                        source=source,
                    )
                )
                written = self.store.write_bars(bars)
                if not bars.empty:
                    self.catalog.upsert(
                        CatalogRecord(
                            symbol=symbol,
                            frequency=frequency,
                            adjust=adjust,
                            start_date=bars["date"].min().date(),
                            end_date=bars["date"].max().date(),
                            rows=len(bars),
                            source=source,
                            cache_path=written[0],
                            updated_at=self.catalog.metadata.now(),
                        )
                    )
                self.tasks.mark_success(task_id)
            except Exception as exc:
                self.tasks.mark_failed(task_id, str(exc))
                raise
```

- [ ] **Step 7: Run data provider tests and confirm they pass**

Run:

```bash
pytest tests/data/test_akshare_provider.py tests/data/test_data_service.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit data provider and sync service**

Run:

```bash
git add backtest/data/provider.py backtest/data/akshare_provider.py backtest/data/service.py tests/data/test_akshare_provider.py tests/data/test_data_service.py
git commit -m "feat: add AkShare data sync service"
```

Expected: commit succeeds.

## Task 7: Signal Providers and Signal Validation

**Files:**

- Create: `backtest/signals/__init__.py`
- Create: `backtest/signals/context.py`
- Create: `backtest/signals/providers.py`
- Create: `backtest/signals/validators.py`
- Create: `tests/signals/test_signal_providers.py`

- [ ] **Step 1: Write signal provider tests**

Create `tests/signals/test_signal_providers.py`:

```python
from pathlib import Path

import pandas as pd

from backtest.signals.context import StrategyContext
from backtest.signals.providers import FileSignalProvider, PythonSignalProvider


def test_file_signal_provider_reads_csv_and_validates(tmp_path: Path):
    path = tmp_path / "signals.csv"
    path.write_text(
        "date,symbol,target_weight\n2025-01-02,000001,0.25\n",
        encoding="utf-8",
    )

    provider = FileSignalProvider(path)
    result = provider.load(stock_pool=["000001.SZ"])

    assert result.loc[0, "symbol"] == "000001.SZ"
    assert result.loc[0, "target_weight"] == 0.25


def test_python_signal_provider_calls_function(tmp_path: Path):
    strategy_path = tmp_path / "strategy.py"
    strategy_path.write_text(
        """
import pandas as pd

def generate_signals(context):
    assert context.stock_pool == ["000001.SZ"]
    return pd.DataFrame({"date": ["2025-01-02"], "symbol": ["000001.SZ"], "target_weight": [0.20]})
""",
        encoding="utf-8",
    )
    context = StrategyContext(
        bars=pd.DataFrame(),
        stock_pool=["000001.SZ"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        params={},
    )

    provider = PythonSignalProvider(strategy_path, function_name="generate_signals")
    result = provider.load(context=context)

    assert result.loc[0, "target_weight"] == 0.20
```

- [ ] **Step 2: Run signal tests and confirm they fail**

Run:

```bash
pytest tests/signals -v
```

Expected: FAIL because signal modules do not exist.

- [ ] **Step 3: Implement StrategyContext**

Create `backtest/signals/context.py`:

```python
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class StrategyContext:
    bars: pd.DataFrame
    stock_pool: list[str]
    start_date: str
    end_date: str
    params: dict[str, Any]
```

- [ ] **Step 4: Implement signal providers**

Create `backtest/signals/providers.py`:

```python
import importlib.util
from pathlib import Path

import pandas as pd

from backtest.core.frames import validate_signal_frame
from backtest.signals.context import StrategyContext


class FileSignalProvider:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self, stock_pool: list[str]) -> pd.DataFrame:
        if self.path.suffix.lower() == ".csv":
            frame = pd.read_csv(self.path)
        elif self.path.suffix.lower() == ".parquet":
            frame = pd.read_parquet(self.path)
        else:
            raise ValueError(f"Unsupported signal file type: {self.path.suffix}")
        return validate_signal_frame(frame, stock_pool=stock_pool)


class PythonSignalProvider:
    def __init__(self, path: str | Path, function_name: str = "generate_signals") -> None:
        self.path = Path(path)
        self.function_name = function_name

    def load(self, context: StrategyContext) -> pd.DataFrame:
        spec = importlib.util.spec_from_file_location("user_strategy", self.path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Cannot load strategy module: {self.path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, self.function_name)
        frame = fn(context)
        return validate_signal_frame(frame, stock_pool=context.stock_pool)
```

Create `backtest/signals/validators.py`:

```python
from backtest.core.frames import validate_signal_frame

__all__ = ["validate_signal_frame"]
```

Create `backtest/signals/__init__.py`:

```python
from backtest.signals.context import StrategyContext
from backtest.signals.providers import FileSignalProvider, PythonSignalProvider

__all__ = ["FileSignalProvider", "PythonSignalProvider", "StrategyContext"]
```

- [ ] **Step 5: Run signal tests and confirm they pass**

Run:

```bash
pytest tests/signals -v
```

Expected: PASS.

- [ ] **Step 6: Commit signal providers**

Run:

```bash
git add backtest/signals tests/signals
git commit -m "feat: add signal providers"
```

Expected: commit succeeds.

## Task 8: Broker Cost, Slippage, and A Share Execution Engine

**Files:**

- Create: `backtest/broker/__init__.py`
- Create: `backtest/broker/costs.py`
- Create: `backtest/broker/slippage.py`
- Create: `backtest/broker/account.py`
- Create: `backtest/broker/execution.py`
- Create: `backtest/broker/engine.py`
- Create: `tests/broker/test_costs.py`
- Create: `tests/broker/test_execution.py`

- [ ] **Step 1: Write cost and slippage tests**

Create `tests/broker/test_costs.py`:

```python
from backtest.broker.costs import AShareCostModel
from backtest.broker.slippage import FixedRateSlippageModel


def test_cost_model_applies_min_commission_and_sell_stamp_tax():
    model = AShareCostModel(commission_rate=0.0003, min_commission=5, stamp_tax_rate=0.0005)

    buy_cost = model.calculate(side="buy", value=1000)
    sell_cost = model.calculate(side="sell", value=1000)

    assert buy_cost.commission == 5
    assert buy_cost.tax == 0
    assert sell_cost.commission == 5
    assert sell_cost.tax == 0.5


def test_fixed_slippage_adjusts_buy_and_sell_prices():
    model = FixedRateSlippageModel(rate=0.001)

    assert model.apply("buy", 10.0) == 10.01
    assert model.apply("sell", 10.0) == 9.99
```

- [ ] **Step 2: Write execution tests for board lot, T+1, and limit rejection**

Create `tests/broker/test_execution.py`:

```python
import pandas as pd

from backtest.broker.engine import BrokerEngine
from backtest.config.models import ExecutionConfig


def make_execution_config() -> ExecutionConfig:
    return ExecutionConfig(
        timing="next_open",
        initial_cash=100000,
        commission_rate=0.0003,
        min_commission=5,
        stamp_tax_rate=0.0005,
        slippage_rate=0.0,
        board_lot_size=100,
    )


def test_broker_buys_in_board_lots_at_next_open():
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "symbol": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 10.0],
            "high": [10.5, 10.5],
            "low": [9.5, 9.5],
            "close": [10.0, 10.0],
            "volume": [10000, 10000],
            "amount": [100000, 100000],
            "frequency": ["1d", "1d"],
            "adjust": ["qfq", "qfq"],
        }
    )
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02"]),
            "symbol": ["000001.SZ"],
            "target_weight": [0.101],
        }
    )

    result = BrokerEngine(make_execution_config()).run(bars=bars, signals=signals)

    filled = result.orders[result.orders["status"] == "filled"].iloc[0]
    assert filled["filled_shares"] == 1000
    assert result.positions.iloc[-1]["shares"] == 1000


def test_broker_blocks_same_day_sell_due_to_t_plus_one():
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "symbol": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 10.0],
            "high": [10.5, 10.5],
            "low": [9.5, 9.5],
            "close": [10.0, 10.0],
            "volume": [10000, 10000],
            "amount": [100000, 100000],
            "frequency": ["1d", "1d"],
            "adjust": ["qfq", "qfq"],
        }
    )
    signals = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-02"]),
            "symbol": ["000001.SZ", "000001.SZ"],
            "target_weight": [0.2, 0.0],
        }
    )

    result = BrokerEngine(make_execution_config()).run(bars=bars, signals=signals)

    rejected = result.orders[result.orders["status"] == "rejected"]
    assert "T+1" in rejected.iloc[0]["reason"]
```

- [ ] **Step 3: Run broker tests and confirm they fail**

Run:

```bash
pytest tests/broker -v
```

Expected: FAIL because broker modules do not exist.

- [ ] **Step 4: Implement cost and slippage models**

Create `backtest/broker/costs.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class TradeCost:
    commission: float
    tax: float

    @property
    def total(self) -> float:
        return self.commission + self.tax


class AShareCostModel:
    def __init__(self, commission_rate: float, min_commission: float, stamp_tax_rate: float) -> None:
        self.commission_rate = commission_rate
        self.min_commission = min_commission
        self.stamp_tax_rate = stamp_tax_rate

    def calculate(self, side: str, value: float) -> TradeCost:
        commission = max(value * self.commission_rate, self.min_commission) if value > 0 else 0.0
        tax = value * self.stamp_tax_rate if side == "sell" else 0.0
        return TradeCost(commission=round(commission, 6), tax=round(tax, 6))
```

Create `backtest/broker/slippage.py`:

```python
class FixedRateSlippageModel:
    def __init__(self, rate: float) -> None:
        self.rate = rate

    def apply(self, side: str, price: float) -> float:
        if side == "buy":
            return round(price * (1 + self.rate), 6)
        if side == "sell":
            return round(price * (1 - self.rate), 6)
        raise ValueError(f"Unsupported side: {side}")
```

- [ ] **Step 5: Implement account and broker result containers**

Create `backtest/broker/account.py`:

```python
from dataclasses import dataclass, field


@dataclass
class Lot:
    shares: int
    available_date: object


@dataclass
class Account:
    cash: float
    positions: dict[str, int] = field(default_factory=dict)
    lots: dict[str, list[Lot]] = field(default_factory=dict)

    def shares(self, symbol: str) -> int:
        return self.positions.get(symbol, 0)

    def add_position(self, symbol: str, shares: int, available_date: object) -> None:
        self.positions[symbol] = self.positions.get(symbol, 0) + shares
        self.lots.setdefault(symbol, []).append(Lot(shares=shares, available_date=available_date))

    def available_shares(self, symbol: str, trade_date: object) -> int:
        return sum(lot.shares for lot in self.lots.get(symbol, []) if lot.available_date <= trade_date)
```

Create `backtest/broker/execution.py`:

```python
from dataclasses import dataclass

import pandas as pd


@dataclass
class BrokerResult:
    equity_curve: pd.DataFrame
    positions: pd.DataFrame
    orders: pd.DataFrame
    trades: pd.DataFrame
```

- [ ] **Step 6: Implement BrokerEngine MVP path**

Create `backtest/broker/engine.py`:

```python
import pandas as pd

from backtest.broker.account import Account
from backtest.broker.costs import AShareCostModel
from backtest.broker.execution import BrokerResult
from backtest.broker.slippage import FixedRateSlippageModel
from backtest.config.models import ExecutionConfig


class BrokerEngine:
    def __init__(self, config: ExecutionConfig) -> None:
        self.config = config
        self.cost_model = AShareCostModel(config.commission_rate, config.min_commission, config.stamp_tax_rate)
        self.slippage_model = FixedRateSlippageModel(config.slippage_rate)

    def run(self, bars: pd.DataFrame, signals: pd.DataFrame) -> BrokerResult:
        account = Account(cash=self.config.initial_cash)
        bars = bars.sort_values(["date", "symbol"]).reset_index(drop=True)
        signals = signals.sort_values(["date", "symbol"]).reset_index(drop=True)
        dates = sorted(bars["date"].drop_duplicates())
        orders: list[dict] = []
        trades: list[dict] = []
        positions: list[dict] = []
        equity_curve: list[dict] = []

        for signal_date, daily_signals in signals.groupby("date"):
            execution_date = self._next_date(dates, signal_date)
            if execution_date is None:
                continue
            day_bars = bars[bars["date"] == execution_date].set_index("symbol")
            equity_before = self._mark_to_market(account, day_bars)
            for signal in daily_signals.itertuples(index=False):
                symbol = signal.symbol
                if symbol not in day_bars.index:
                    orders.append(self._rejected(execution_date, symbol, "buy", 0, "missing execution bar"))
                    continue
                bar = day_bars.loc[symbol]
                current_value = account.shares(symbol) * float(bar["open"])
                target_value = equity_before * float(signal.target_weight)
                delta_value = target_value - current_value
                if abs(delta_value) < 1e-9:
                    continue
                side = "buy" if delta_value > 0 else "sell"
                price = self.slippage_model.apply(side, float(bar["open"]))
                requested_shares = int(abs(delta_value) / price)
                requested_shares = (requested_shares // self.config.board_lot_size) * self.config.board_lot_size
                if requested_shares <= 0:
                    orders.append(self._rejected(execution_date, symbol, side, 0, "below board lot"))
                    continue
                if side == "buy":
                    filled = self._buy(account, execution_date, symbol, requested_shares, price, orders, trades)
                else:
                    filled = self._sell(account, execution_date, symbol, requested_shares, price, orders, trades)
                if filled:
                    positions.append({"date": execution_date, "symbol": symbol, "shares": account.shares(symbol)})
            day_bars_after = bars[bars["date"] == execution_date].set_index("symbol")
            equity_curve.append({"date": execution_date, "equity": self._mark_to_market(account, day_bars_after), "cash": account.cash})

        return BrokerResult(
            equity_curve=pd.DataFrame(equity_curve),
            positions=pd.DataFrame(positions),
            orders=pd.DataFrame(orders),
            trades=pd.DataFrame(trades),
        )

    def _next_date(self, dates: list[pd.Timestamp], signal_date: pd.Timestamp) -> pd.Timestamp | None:
        for date_value in dates:
            if date_value > signal_date:
                return date_value
        return None

    def _mark_to_market(self, account: Account, day_bars: pd.DataFrame) -> float:
        value = account.cash
        for symbol, shares in account.positions.items():
            if symbol in day_bars.index:
                value += shares * float(day_bars.loc[symbol, "close"])
        return value

    def _buy(self, account: Account, trade_date, symbol: str, shares: int, price: float, orders: list[dict], trades: list[dict]) -> bool:
        value = shares * price
        cost = self.cost_model.calculate("buy", value)
        affordable = int((account.cash - cost.total) / price)
        affordable = (affordable // self.config.board_lot_size) * self.config.board_lot_size
        filled_shares = min(shares, affordable)
        if filled_shares <= 0:
            orders.append(self._rejected(trade_date, symbol, "buy", shares, "cash insufficient"))
            return False
        value = filled_shares * price
        cost = self.cost_model.calculate("buy", value)
        account.cash -= value + cost.total
        account.add_position(symbol, filled_shares, available_date=trade_date + pd.Timedelta(days=1))
        orders.append(self._filled(trade_date, symbol, "buy", shares, filled_shares, price, cost.commission, cost.tax))
        trades.append({"date": trade_date, "symbol": symbol, "side": "buy", "shares": filled_shares, "price": price})
        return True

    def _sell(self, account: Account, trade_date, symbol: str, shares: int, price: float, orders: list[dict], trades: list[dict]) -> bool:
        available = account.available_shares(symbol, trade_date)
        if available <= 0:
            orders.append(self._rejected(trade_date, symbol, "sell", shares, "T+1 available shares are zero"))
            return False
        filled_shares = min(shares, available)
        value = filled_shares * price
        cost = self.cost_model.calculate("sell", value)
        account.cash += value - cost.total
        account.positions[symbol] = account.positions.get(symbol, 0) - filled_shares
        orders.append(self._filled(trade_date, symbol, "sell", shares, filled_shares, price, cost.commission, cost.tax))
        trades.append({"date": trade_date, "symbol": symbol, "side": "sell", "shares": filled_shares, "price": price})
        return True

    def _filled(self, date, symbol: str, side: str, requested: int, filled: int, price: float, commission: float, tax: float) -> dict:
        status = "filled" if requested == filled else "adjusted"
        return {
            "date": date,
            "symbol": symbol,
            "side": side,
            "requested_shares": requested,
            "filled_shares": filled,
            "price": price,
            "commission": commission,
            "tax": tax,
            "slippage_cost": 0.0,
            "status": status,
            "reason": "",
        }

    def _rejected(self, date, symbol: str, side: str, requested: int, reason: str) -> dict:
        return {
            "date": date,
            "symbol": symbol,
            "side": side,
            "requested_shares": requested,
            "filled_shares": 0,
            "price": 0.0,
            "commission": 0.0,
            "tax": 0.0,
            "slippage_cost": 0.0,
            "status": "rejected",
            "reason": reason,
        }
```

Create `backtest/broker/__init__.py`:

```python
from backtest.broker.engine import BrokerEngine
from backtest.broker.execution import BrokerResult

__all__ = ["BrokerEngine", "BrokerResult"]
```

- [ ] **Step 7: Run broker tests and confirm they pass**

Run:

```bash
pytest tests/broker -v
```

Expected: PASS.

- [ ] **Step 8: Commit broker engine**

Run:

```bash
git add backtest/broker tests/broker
git commit -m "feat: add A share broker execution"
```

Expected: commit succeeds.

## Task 9: Metrics, Custom Metric Registry, and Result Context

**Files:**

- Create: `backtest/metrics/__init__.py`
- Create: `backtest/metrics/context.py`
- Create: `backtest/metrics/results.py`
- Create: `backtest/metrics/builtin.py`
- Create: `backtest/metrics/registry.py`
- Create: `tests/metrics/test_builtin_metrics.py`
- Create: `tests/metrics/test_metric_registry.py`

- [ ] **Step 1: Write built-in metrics tests**

Create `tests/metrics/test_builtin_metrics.py`:

```python
import pandas as pd

from backtest.metrics.builtin import calculate_builtin_metrics
from backtest.metrics.context import BacktestResultContext


def test_builtin_metrics_include_total_return_and_max_drawdown():
    context = BacktestResultContext(
        equity_curve=pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
                "equity": [100.0, 110.0, 99.0],
                "cash": [100.0, 50.0, 40.0],
            }
        ),
        positions=pd.DataFrame(),
        trades=pd.DataFrame(),
        orders=pd.DataFrame(),
        bars=pd.DataFrame(),
        config={},
    )

    metrics = calculate_builtin_metrics(context, names=["total_return", "max_drawdown"])

    assert metrics["total_return"] == -0.01
    assert metrics["max_drawdown"] == -0.10
```

- [ ] **Step 2: Write custom metric registry test**

Create `tests/metrics/test_metric_registry.py`:

```python
from pathlib import Path

import pandas as pd

from backtest.metrics.context import BacktestResultContext
from backtest.metrics.registry import MetricRegistry


def test_metric_registry_loads_custom_metric(tmp_path: Path):
    metric_path = tmp_path / "custom_metric.py"
    metric_path.write_text(
        """
from backtest.core.enums import MetricResultKind
from backtest.core.contracts import MetricResult

class MyMetric:
    name = "my_metric"

    def calculate(self, context):
        return MetricResult(name=self.name, kind=MetricResultKind.SCALAR, value=42)
""",
        encoding="utf-8",
    )
    context = BacktestResultContext(
        equity_curve=pd.DataFrame(),
        positions=pd.DataFrame(),
        trades=pd.DataFrame(),
        orders=pd.DataFrame(),
        bars=pd.DataFrame(),
        config={},
    )

    registry = MetricRegistry()
    registry.load_custom(path=metric_path, class_name="MyMetric")
    results = registry.calculate(context)

    assert results["my_metric"].value == 42
```

- [ ] **Step 3: Run metrics tests and confirm they fail**

Run:

```bash
pytest tests/metrics -v
```

Expected: FAIL because metrics modules do not exist.

- [ ] **Step 4: Implement metric context and built-ins**

Create `backtest/metrics/context.py`:

```python
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class BacktestResultContext:
    equity_curve: pd.DataFrame
    positions: pd.DataFrame
    trades: pd.DataFrame
    orders: pd.DataFrame
    bars: pd.DataFrame
    config: dict[str, Any]
```

Create `backtest/metrics/builtin.py`:

```python
import pandas as pd

from backtest.metrics.context import BacktestResultContext


def calculate_builtin_metrics(context: BacktestResultContext, names: list[str]) -> dict[str, float]:
    equity = context.equity_curve["equity"].astype(float)
    returns = equity.pct_change().dropna()
    available = {
        "total_return": _total_return(equity),
        "annualized_return": _annualized_return(equity),
        "annualized_volatility": _annualized_volatility(returns),
        "max_drawdown": _max_drawdown(equity),
        "sharpe_ratio": _sharpe_ratio(returns),
        "trade_count": float(len(context.trades)),
        "cash_ratio": _cash_ratio(context.equity_curve),
    }
    return {name: available[name] for name in names if name in available}


def _total_return(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    return round(float(equity.iloc[-1] / equity.iloc[0] - 1), 10)


def _annualized_return(equity: pd.Series) -> float:
    if len(equity) < 2:
        return 0.0
    total = equity.iloc[-1] / equity.iloc[0]
    years = len(equity) / 252
    return round(float(total ** (1 / years) - 1), 10)


def _annualized_volatility(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    return round(float(returns.std(ddof=0) * (252 ** 0.5)), 10)


def _max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    drawdown = equity / equity.cummax() - 1
    return round(float(drawdown.min()), 10)


def _sharpe_ratio(returns: pd.Series) -> float:
    if returns.empty or returns.std(ddof=0) == 0:
        return 0.0
    return round(float((returns.mean() / returns.std(ddof=0)) * (252 ** 0.5)), 10)


def _cash_ratio(equity_curve: pd.DataFrame) -> float:
    if equity_curve.empty or "cash" not in equity_curve:
        return 0.0
    latest = equity_curve.iloc[-1]
    return round(float(latest["cash"] / latest["equity"]), 10)
```

- [ ] **Step 5: Implement metric registry**

Create `backtest/metrics/registry.py`:

```python
import importlib.util
from pathlib import Path
from typing import Protocol

from backtest.core.contracts import MetricResult
from backtest.metrics.context import BacktestResultContext


class Metric(Protocol):
    name: str

    def calculate(self, context: BacktestResultContext) -> MetricResult:
        raise NotImplementedError


class MetricRegistry:
    def __init__(self) -> None:
        self._metrics: list[Metric] = []

    def register(self, metric: Metric) -> None:
        self._metrics.append(metric)

    def load_custom(self, path: str | Path, class_name: str) -> None:
        module_path = Path(path)
        spec = importlib.util.spec_from_file_location(f"custom_metric_{module_path.stem}", module_path)
        if spec is None or spec.loader is None:
            raise ValueError(f"Cannot load metric module: {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        metric_class = getattr(module, class_name)
        self.register(metric_class())

    def calculate(self, context: BacktestResultContext) -> dict[str, MetricResult]:
        results: dict[str, MetricResult] = {}
        for metric in self._metrics:
            result = metric.calculate(context)
            results[result.name] = result
        return results
```

Create `backtest/metrics/results.py`:

```python
from backtest.core.contracts import MetricResult

__all__ = ["MetricResult"]
```

Create `backtest/metrics/__init__.py`:

```python
from backtest.metrics.builtin import calculate_builtin_metrics
from backtest.metrics.context import BacktestResultContext
from backtest.metrics.registry import MetricRegistry

__all__ = ["BacktestResultContext", "MetricRegistry", "calculate_builtin_metrics"]
```

- [ ] **Step 6: Run metrics tests and confirm they pass**

Run:

```bash
pytest tests/metrics -v
```

Expected: PASS.

- [ ] **Step 7: Commit metrics**

Run:

```bash
git add backtest/metrics tests/metrics
git commit -m "feat: add metrics registry"
```

Expected: commit succeeds.

## Task 10: Reports, Run Manifest, and GUI-Ready Outputs

**Files:**

- Create: `backtest/reports/__init__.py`
- Create: `backtest/reports/manifest.py`
- Create: `backtest/reports/writer.py`
- Create: `backtest/reports/html.py`
- Create: `tests/reports/test_reports.py`

- [ ] **Step 1: Write report output test**

Create `tests/reports/test_reports.py`:

```python
from pathlib import Path

import pandas as pd

from backtest.broker.execution import BrokerResult
from backtest.reports.manifest import build_manifest
from backtest.reports.writer import FileReportWriter


def test_file_report_writer_outputs_structured_files(tmp_path: Path):
    result = BrokerResult(
        equity_curve=pd.DataFrame({"date": pd.to_datetime(["2025-01-02"]), "equity": [100000.0], "cash": [100000.0]}),
        positions=pd.DataFrame({"date": [], "symbol": [], "shares": []}),
        orders=pd.DataFrame({"date": [], "symbol": [], "status": []}),
        trades=pd.DataFrame({"date": [], "symbol": [], "side": []}),
    )
    manifest = build_manifest(
        run_id="demo",
        project_name="demo",
        config_path=Path("configs/demo.yaml"),
        config_hash="abc",
        signal_source="file",
        data_source="fixture",
        symbols=["000001.SZ"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
    )

    writer = FileReportWriter(tmp_path)
    run_dir = writer.write(run_id="demo", broker_result=result, metrics={"total_return": 0.0}, manifest=manifest)

    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "equity_curve.parquet").exists()
    assert (run_dir / "report.html").exists()
```

- [ ] **Step 2: Run report tests and confirm they fail**

Run:

```bash
pytest tests/reports -v
```

Expected: FAIL because report modules do not exist.

- [ ] **Step 3: Implement manifest builder**

Create `backtest/reports/manifest.py`:

```python
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_manifest(
    run_id: str,
    project_name: str,
    config_path: Path,
    config_hash: str,
    signal_source: str,
    data_source: str,
    symbols: list[str],
    start_date: str,
    end_date: str,
    benchmark: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "project_name": project_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path),
        "config_hash": config_hash,
        "signal_source": signal_source,
        "data_source": data_source,
        "symbols": symbols,
        "start_date": start_date,
        "end_date": end_date,
        "benchmark": benchmark,
        "engine_version": "0.1.0",
    }
```

- [ ] **Step 4: Implement HTML report rendering**

Create `backtest/reports/html.py`:

```python
from typing import Any

HTML_TEMPLATE = """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{{ title }}</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #17202a; }
    .metric { display: inline-block; padding: 12px 16px; margin: 8px; background: #f4f6f7; border-radius: 8px; }
    table { border-collapse: collapse; margin-top: 16px; }
    td, th { border: 1px solid #d5dbdb; padding: 6px 10px; }
  </style>
</head>
<body>
  <h1>{{ title }}</h1>
  <h2>核心指标</h2>
  {% for name, value in metrics.items() %}
  <div class="metric"><strong>{{ name }}</strong>: {{ value }}</div>
  {% endfor %}
  <h2>运行信息</h2>
  <table>
    {% for name, value in manifest.items() %}
    <tr><th>{{ name }}</th><td>{{ value }}</td></tr>
    {% endfor %}
  </table>
</body>
</html>
"""


def render_html_report(title: str, metrics: dict[str, Any], manifest: dict[str, Any]) -> str:
    from jinja2 import Template

    return Template(HTML_TEMPLATE).render(title=title, metrics=metrics, manifest=manifest)
```

- [ ] **Step 5: Implement FileReportWriter**

Create `backtest/reports/writer.py`:

```python
import json
from pathlib import Path
from typing import Any

from backtest.broker.execution import BrokerResult
from backtest.reports.html import render_html_report


class FileReportWriter:
    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)

    def write(
        self,
        run_id: str,
        broker_result: BrokerResult,
        metrics: dict[str, Any],
        manifest: dict[str, Any],
    ) -> Path:
        run_dir = self.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (run_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        broker_result.equity_curve.to_parquet(run_dir / "equity_curve.parquet", index=False)
        broker_result.positions.to_parquet(run_dir / "positions.parquet", index=False)
        broker_result.orders.to_parquet(run_dir / "orders.parquet", index=False)
        broker_result.trades.to_parquet(run_dir / "trades.parquet", index=False)
        html = render_html_report(title=f"Backtest Report: {run_id}", metrics=metrics, manifest=manifest)
        (run_dir / "report.html").write_text(html, encoding="utf-8")
        return run_dir
```

Create `backtest/reports/__init__.py`:

```python
from backtest.reports.manifest import build_manifest
from backtest.reports.writer import FileReportWriter

__all__ = ["FileReportWriter", "build_manifest"]
```

- [ ] **Step 6: Run report tests and confirm they pass**

Run:

```bash
pytest tests/reports -v
```

Expected: PASS.

- [ ] **Step 7: Commit reports**

Run:

```bash
git add backtest/reports tests/reports
git commit -m "feat: add report outputs"
```

Expected: commit succeeds.

## Task 11: Backtest Orchestrator and Run CLI

**Files:**

- Create: `backtest/engine.py`
- Create: `backtest/cli/run.py`
- Modify: `backtest/cli/app.py`
- Create: `tests/test_engine_e2e.py`

- [ ] **Step 1: Write deterministic end-to-end engine test**

Create `tests/test_engine_e2e.py`:

```python
from pathlib import Path

import pandas as pd

from backtest.config.loader import load_config
from backtest.engine import BacktestEngine


def test_backtest_engine_runs_from_file_signals(tmp_path: Path):
    data_dir = tmp_path / "data"
    signals_path = tmp_path / "signals.csv"
    config_path = tmp_path / "config.yaml"
    signals_path.write_text(
        "date,symbol,target_weight\n2025-01-02,000001.SZ,0.5\n",
        encoding="utf-8",
    )
    config_path.write_text(
        f"""
project:
  name: e2e
data:
  source: fixture
  frequency: 1d
  adjust: qfq
  start_date: "2025-01-02"
  end_date: "2025-01-03"
  stock_pool:
    symbols:
      - "000001.SZ"
signals:
  type: file
  path: "{signals_path}"
execution:
  timing: next_open
  initial_cash: 100000
  commission_rate: 0.0003
  min_commission: 5
  stamp_tax_rate: 0.0005
  slippage_rate: 0.0
  board_lot_size: 100
metrics:
  builtin:
    - total_return
    - max_drawdown
report:
  output_dir: "{tmp_path / "runs"}"
  html: true
  charts: true
""",
        encoding="utf-8",
    )
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
            "symbol": ["000001.SZ", "000001.SZ"],
            "open": [10.0, 10.0],
            "high": [10.5, 10.5],
            "low": [9.5, 9.5],
            "close": [10.0, 10.0],
            "volume": [10000, 10000],
            "amount": [100000.0, 100000.0],
            "frequency": ["1d", "1d"],
            "adjust": ["qfq", "qfq"],
        }
    )
    data_dir.mkdir()

    config = load_config(config_path)
    engine = BacktestEngine(config=config, bars_override=bars, config_path=config_path)
    run_dir = engine.run()

    assert (run_dir / "report.html").exists()
    assert (run_dir / "metrics.json").exists()
    assert (run_dir / "orders.parquet").exists()
```

- [ ] **Step 2: Run E2E test and confirm it fails**

Run:

```bash
pytest tests/test_engine_e2e.py -v
```

Expected: FAIL because `BacktestEngine` does not exist.

- [ ] **Step 3: Implement BacktestEngine orchestration**

Create `backtest/engine.py`:

```python
import hashlib
from pathlib import Path

import pandas as pd

from backtest.broker.engine import BrokerEngine
from backtest.config.models import BacktestConfig
from backtest.metrics.builtin import calculate_builtin_metrics
from backtest.metrics.context import BacktestResultContext
from backtest.reports.manifest import build_manifest
from backtest.reports.writer import FileReportWriter
from backtest.signals.context import StrategyContext
from backtest.signals.providers import FileSignalProvider, PythonSignalProvider


class BacktestEngine:
    def __init__(self, config: BacktestConfig, config_path: Path, bars_override: pd.DataFrame | None = None) -> None:
        self.config = config
        self.config_path = Path(config_path)
        self.bars_override = bars_override

    def run(self) -> Path:
        bars = self._load_bars()
        signals = self._load_signals(bars)
        broker_result = BrokerEngine(self.config.execution).run(bars=bars, signals=signals)
        context = BacktestResultContext(
            equity_curve=broker_result.equity_curve,
            positions=broker_result.positions,
            trades=broker_result.trades,
            orders=broker_result.orders,
            bars=bars,
            config=self.config.model_dump(mode="json"),
        )
        metrics = calculate_builtin_metrics(context, self.config.metrics.builtin)
        run_id = self._run_id()
        manifest = build_manifest(
            run_id=run_id,
            project_name=self.config.project.name,
            config_path=self.config_path,
            config_hash=self._file_hash(self.config_path),
            signal_source=self.config.signals.type,
            data_source=self.config.data.source,
            symbols=self.config.data.stock_pool.symbols,
            start_date=self.config.data.start_date.isoformat(),
            end_date=self.config.data.end_date.isoformat(),
        )
        return FileReportWriter(self.config.report.output_dir).write(run_id, broker_result, metrics, manifest)

    def _load_bars(self) -> pd.DataFrame:
        if self.bars_override is not None:
            return self.bars_override
        raise ValueError("BacktestEngine requires cached bar loading to be wired by CLI data task")

    def _load_signals(self, bars: pd.DataFrame) -> pd.DataFrame:
        if self.config.signals.type == "file":
            return FileSignalProvider(self.config.signals.path).load(stock_pool=self.config.data.stock_pool.symbols)
        context = StrategyContext(
            bars=bars,
            stock_pool=self.config.data.stock_pool.symbols,
            start_date=self.config.data.start_date.isoformat(),
            end_date=self.config.data.end_date.isoformat(),
            params={},
        )
        return PythonSignalProvider(self.config.signals.path, self.config.signals.function).load(context=context)

    def _run_id(self) -> str:
        return f"{pd.Timestamp.utcnow().strftime('%Y%m%d_%H%M%S')}_{self.config.project.name}"

    def _file_hash(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
```

- [ ] **Step 4: Add run CLI command**

Create `backtest/cli/run.py`:

```python
from pathlib import Path

import typer

from backtest.config.loader import load_config
from backtest.engine import BacktestEngine

app = typer.Typer(help="Run backtests and write reports")


@app.command("run")
def run_backtest(config: Path = typer.Option(Path("configs/demo.yaml"), "--config", exists=True, readable=True)) -> None:
    loaded = load_config(config)
    run_dir = BacktestEngine(config=loaded, config_path=config).run()
    typer.echo(f"Backtest run written to {run_dir}")
```

Modify `backtest/cli/app.py`:

```python
import typer

from backtest.cli import run

app = typer.Typer(help="A Share backtest research CLI")
app.add_typer(run.app, name="backtest")


@app.callback()
def root() -> None:
    """Run data ingestion, backtests, validation, and reports."""


def main() -> None:
    app()
```

- [ ] **Step 5: Run E2E test and confirm it passes**

Run:

```bash
pytest tests/test_engine_e2e.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit orchestrator**

Run:

```bash
git add backtest/engine.py backtest/cli/run.py backtest/cli/app.py tests/test_engine_e2e.py
git commit -m "feat: add backtest orchestration"
```

Expected: commit succeeds.

## Task 12: Data, Validation, and Inventory CLI Commands

**Files:**

- Create: `backtest/cli/data.py`
- Create: `backtest/cli/validate.py`
- Modify: `backtest/cli/app.py`
- Modify: `backtest/data/tasks.py`
- Create: `tests/test_cli_commands.py`

- [ ] **Step 1: Write CLI command tests**

Create `tests/test_cli_commands.py`:

```python
from datetime import date
from pathlib import Path

from typer.testing import CliRunner

from backtest.cli.app import app
from backtest.core.enums import AdjustMode, Frequency
from backtest.data.metadata import MetadataStore
from backtest.data.tasks import CrawlTaskManager


def test_validate_config_cli_accepts_valid_config(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    signal_path = tmp_path / "signals.csv"
    signal_path.write_text("date,symbol,target_weight\n2025-01-02,000001.SZ,0.1\n", encoding="utf-8")
    config_path.write_text(
        f"""
project:
  name: cli
data:
  source: akshare
  frequency: 1d
  adjust: qfq
  start_date: "2025-01-01"
  end_date: "2025-01-31"
  stock_pool:
    symbols:
      - "000001.SZ"
signals:
  type: file
  path: "{signal_path}"
execution:
  timing: next_open
  initial_cash: 100000
  commission_rate: 0.0003
  min_commission: 5
  stamp_tax_rate: 0.0005
  slippage_rate: 0.0005
  board_lot_size: 100
metrics:
  builtin:
    - total_return
report:
  output_dir: runs
  html: true
  charts: true
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, ["validate", "config", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Config is valid" in result.output


def test_data_inventory_cli_handles_empty_metadata(tmp_path: Path):
    result = CliRunner().invoke(app, ["data", "inventory", "--metadata", str(tmp_path / "metadata.sqlite")])

    assert result.exit_code == 0
    assert "No cached data" in result.output


def test_data_coverage_cli_prints_missing_ranges(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    signal_path = tmp_path / "signals.csv"
    signal_path.write_text("date,symbol,target_weight\n2025-01-02,000001.SZ,0.1\n", encoding="utf-8")
    config_path.write_text(
        f"""
project:
  name: coverage
data:
  source: akshare
  frequency: 1d
  adjust: qfq
  start_date: "2025-01-01"
  end_date: "2025-01-31"
  stock_pool:
    symbols:
      - "000001.SZ"
signals:
  type: file
  path: "{signal_path}"
execution:
  timing: next_open
  initial_cash: 100000
  commission_rate: 0.0003
  min_commission: 5
  stamp_tax_rate: 0.0005
  slippage_rate: 0.0005
  board_lot_size: 100
metrics:
  builtin:
    - total_return
report:
  output_dir: runs
  html: true
  charts: true
""",
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        ["data", "coverage", "--config", str(config_path), "--metadata", str(tmp_path / "metadata.sqlite")],
    )

    assert result.exit_code == 0
    assert "000001.SZ missing 2025-01-01 to 2025-01-31" in result.output


def test_data_retry_cli_marks_failed_tasks_retrying(tmp_path: Path):
    metadata_path = tmp_path / "metadata.sqlite"
    metadata = MetadataStore(metadata_path)
    manager = CrawlTaskManager(metadata)
    task_id = manager.create_task(
        symbol="000001.SZ",
        frequency=Frequency.DAILY,
        adjust=AdjustMode.QFQ,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 31),
        source="fixture",
    )
    manager.mark_running(task_id)
    manager.mark_failed(task_id, "timeout")

    result = CliRunner().invoke(app, ["data", "retry", "--failed", "--metadata", str(metadata_path)])

    assert result.exit_code == 0
    assert f"Queued retry for task {task_id}" in result.output
    assert CrawlTaskManager(metadata).list_tasks()[0].status == "retrying"
```

- [ ] **Step 2: Run CLI tests and confirm they fail**

Run:

```bash
pytest tests/test_cli_commands.py -v
```

Expected: FAIL because data and validate CLI modules do not exist.

- [ ] **Step 3: Add retrying state transition to CrawlTaskManager**

Modify `backtest/data/tasks.py` by adding this method inside `CrawlTaskManager`:

```python
    def mark_retrying(self, task_id: int) -> None:
        now = self.metadata.now().isoformat()
        with self.metadata.connect() as conn:
            conn.execute(
                """
                UPDATE crawl_tasks
                SET status = 'retrying', updated_at = ?, last_error = NULL
                WHERE task_id = ?
                """,
                (now, task_id),
            )
```

- [ ] **Step 4: Implement validate CLI**

Create `backtest/cli/validate.py`:

```python
from pathlib import Path

import typer

from backtest.config.loader import load_config
from backtest.signals.providers import FileSignalProvider

app = typer.Typer(help="Validate configs and signal files")


@app.command("config")
def validate_config(config: Path = typer.Option(Path("configs/demo.yaml"), "--config", exists=True, readable=True)) -> None:
    load_config(config)
    typer.echo("Config is valid")


@app.command("signals")
def validate_signals(
    path: Path = typer.Option(Path("signals/demo_signals.csv"), "--path", exists=True, readable=True),
    symbol: list[str] = typer.Option([], "--symbol"),
) -> None:
    FileSignalProvider(path).load(stock_pool=list(symbol) if symbol else [])
    typer.echo("Signals are valid")
```

- [ ] **Step 5: Implement data sync, inventory, coverage, tasks, and retry CLI**

Create `backtest/cli/data.py`:

```python
from pathlib import Path

import typer

from backtest.config.loader import load_config
from backtest.data.akshare_provider import AkShareProvider
from backtest.data.catalog import DataCatalog
from backtest.data.metadata import MetadataStore
from backtest.data.service import DataSyncService
from backtest.data.store import ParquetBarStore
from backtest.data.tasks import CrawlTaskManager

app = typer.Typer(help="Manage market data cache, catalog, and crawl tasks")


@app.command("sync")
def sync(
    config: Path = typer.Option(Path("configs/demo.yaml"), "--config", exists=True, readable=True),
    metadata: Path = typer.Option(Path("data/metadata.sqlite"), "--metadata"),
    bars_root: Path = typer.Option(Path("data/bars"), "--bars-root"),
) -> None:
    loaded = load_config(config)
    if loaded.data.source != "akshare":
        raise typer.BadParameter("MVP data sync CLI supports source=akshare")
    store = MetadataStore(metadata)
    service = DataSyncService(
        provider=AkShareProvider(),
        store=ParquetBarStore(bars_root),
        catalog=DataCatalog(store),
        tasks=CrawlTaskManager(store),
    )
    service.sync(
        symbols=loaded.data.stock_pool.symbols,
        start_date=loaded.data.start_date,
        end_date=loaded.data.end_date,
        frequency=loaded.data.frequency,
        adjust=loaded.data.adjust,
        source=loaded.data.source,
    )
    typer.echo("Data sync complete")


@app.command("inventory")
def inventory(metadata: Path = typer.Option(Path("data/metadata.sqlite"), "--metadata")) -> None:
    catalog = DataCatalog(MetadataStore(metadata))
    records = catalog.inventory()
    if not records:
        typer.echo("No cached data")
        return
    for record in records:
        typer.echo(f"{record.symbol} {record.frequency.value} {record.adjust.value} {record.start_date} {record.end_date} rows={record.rows}")


@app.command("coverage")
def coverage(
    config: Path = typer.Option(Path("configs/demo.yaml"), "--config", exists=True, readable=True),
    metadata: Path = typer.Option(Path("data/metadata.sqlite"), "--metadata"),
) -> None:
    loaded = load_config(config)
    catalog = DataCatalog(MetadataStore(metadata))
    missing = catalog.missing_ranges(
        symbols=loaded.data.stock_pool.symbols,
        start_date=loaded.data.start_date,
        end_date=loaded.data.end_date,
        frequency=loaded.data.frequency,
        adjust=loaded.data.adjust,
    )
    if not missing:
        typer.echo("Data coverage complete")
        return
    for symbol, start_date, end_date in missing:
        typer.echo(f"{symbol} missing {start_date} to {end_date}")


@app.command("tasks")
def tasks(metadata: Path = typer.Option(Path("data/metadata.sqlite"), "--metadata")) -> None:
    manager = CrawlTaskManager(MetadataStore(metadata))
    records = manager.list_tasks()
    if not records:
        typer.echo("No crawl tasks")
        return
    for record in records:
        typer.echo(f"{record.task_id} {record.symbol} {record.status} attempts={record.attempts}")


@app.command("retry")
def retry(
    failed: bool = typer.Option(False, "--failed"),
    metadata: Path = typer.Option(Path("data/metadata.sqlite"), "--metadata"),
) -> None:
    if not failed:
        raise typer.BadParameter("Use --failed to retry failed crawl tasks")
    manager = CrawlTaskManager(MetadataStore(metadata))
    records = manager.failed_tasks()
    if not records:
        typer.echo("No failed tasks")
        return
    for record in records:
        manager.mark_retrying(record.task_id)
        typer.echo(f"Queued retry for task {record.task_id}")
```

- [ ] **Step 6: Wire CLI modules into root app**

Modify `backtest/cli/app.py`:

```python
import typer

from backtest.cli import data, run, validate

app = typer.Typer(help="A Share backtest research CLI")
app.add_typer(data.app, name="data")
app.add_typer(run.app, name="backtest")
app.add_typer(validate.app, name="validate")


@app.callback()
def root() -> None:
    """Run data ingestion, backtests, validation, and reports."""


def main() -> None:
    app()
```

- [ ] **Step 7: Run CLI tests and confirm they pass**

Run:

```bash
pytest tests/test_cli_commands.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit CLI commands**

Run:

```bash
git add backtest/cli backtest/data/tasks.py tests/test_cli_commands.py
git commit -m "feat: add validation and data CLI"
```

Expected: commit succeeds.

## Task 13: Documentation Deliverables

**Files:**

- Create: `README.md`
- Create: `docs/architecture.md`
- Create: `docs/data-ingestion.md`
- Create: `docs/data-contracts.md`
- Create: `docs/signal-integration.md`
- Create: `docs/metrics-extension.md`
- Create: `docs/reports.md`
- Create: `docs/cli.md`
- Create: `docs/ai-handoff.md`

- [ ] **Step 1: Write README with minimal workflow**

Create `README.md`:

````markdown
# A Share Backtest

Local research-first A share backtesting toolkit.

## What It Does

- Fetches and caches A share OHLCV data.
- Tracks cached data coverage and crawl task state.
- Loads trading signals from Python strategy files or CSV/Parquet files.
- Runs target-weight backtests with A share execution constraints.
- Exports metrics, structured result files, and an HTML report.

## Minimal Workflow

```bash
pip install -e ".[dev]"
backtest validate config --config configs/demo.yaml
backtest data inventory
backtest backtest run --config configs/demo.yaml
```

## Key Docs

- `docs/architecture.md`
- `docs/data-contracts.md`
- `docs/data-ingestion.md`
- `docs/signal-integration.md`
- `docs/metrics-extension.md`
- `docs/ai-handoff.md`
````

- [ ] **Step 2: Write architecture doc**

Create `docs/architecture.md`:

````markdown
# Architecture

The MVP is a Python package plus CLI.

Core flow:

```text
DataProvider -> CrawlTaskManager -> BarStore -> SignalProvider -> Broker -> Metrics -> Reports
                                      |
                                      v
                                  DataCatalog
```

## Extension Points

- `DataProvider`: external market data source.
- `BarStore`: local bar storage.
- `SignalProvider`: signal source.
- `ExecutionModel`: signal-to-order behavior.
- `CostModel`: commission and tax model.
- `SlippageModel`: execution price adjustment.
- `Metric`: custom strategy evaluation.
- `ReportWriter`: output destination.

## Change Guidance

- Add new data sources under `backtest/data/`.
- Add new signal inputs under `backtest/signals/`.
- Add new execution rules under `backtest/broker/`.
- Add new metrics under `backtest/metrics/`.
- Add new outputs under `backtest/reports/`.
````

- [ ] **Step 3: Write data ingestion doc**

Create `docs/data-ingestion.md`:

````markdown
# Data Ingestion

Market bars are cached in Parquet. Metadata is stored in SQLite.

## Cache

```text
data/bars/frequency=1d/adjust=qfq/symbol=000001.SZ/year=2025/bars.parquet
```

## Catalog

`DataCatalog` answers:

- Which symbols are cached.
- Which date ranges are covered.
- Which requested ranges are missing.
- Which file paths contain cached bars.

## Crawl Tasks

`CrawlTaskManager` stores:

- `pending`
- `running`
- `success`
- `failed`
- `cancelled`
- `retrying`

Use:

```bash
backtest data inventory
backtest data tasks
```
````

- [ ] **Step 4: Write contracts and integration docs**

Create `docs/data-contracts.md`:

````markdown
# Data Contracts

## BarFrame

Required columns:

```text
date,symbol,open,high,low,close,volume,amount,frequency,adjust
```

## SignalFrame

Required columns:

```text
date,symbol,target_weight
```

`target_weight` is the desired portfolio weight at the configured execution time.

## Existing Data Conversion

Existing CSV or Parquet bar data must be renamed into `BarFrame` columns.
Existing signal files must be renamed into `SignalFrame` columns.
All symbols should use `000001.SZ` or `600519.SH` format.
````

Create `docs/signal-integration.md`:

````markdown
# Signal Integration

## File Signals

```csv
date,symbol,target_weight
2025-01-02,000001.SZ,0.10
```

## Python Signals

```python
import pandas as pd

def generate_signals(context):
    return pd.DataFrame(
        {
            "date": ["2025-01-02"],
            "symbol": ["000001.SZ"],
            "target_weight": [0.10],
        }
    )
```

Signals are validated before execution. Invalid weights, duplicate rows, and symbols outside the stock pool fail fast.
````

- [ ] **Step 5: Write metrics, reports, CLI, and AI handoff docs**

Create `docs/metrics-extension.md`:

````markdown
# Metrics Extension

Custom metrics implement:

```python
class MyMetric:
    name = "my_metric"

    def calculate(self, context):
        return MetricResult(name=self.name, kind=MetricResultKind.SCALAR, value=1.0)
```

Metric result kinds:

- `scalar`
- `series`
- `table`
````

Create `docs/reports.md`:

````markdown
# Reports

Each run writes:

```text
manifest.json
metrics.json
equity_curve.parquet
positions.parquet
orders.parquet
trades.parquet
report.html
```

Future GUI tools should read these structured files rather than scraping HTML.
````

Create `docs/cli.md`:

````markdown
# CLI

```bash
backtest validate config --config configs/demo.yaml
backtest validate signals --path signals/demo.csv --symbol 000001.SZ
backtest data inventory
backtest data tasks
backtest backtest run --config configs/demo.yaml
```
````

Create `docs/ai-handoff.md`:

````markdown
# AI Handoff

Read these first:

```text
README.md
docs/architecture.md
docs/data-contracts.md
docs/ai-handoff.md
```

Rules:

- Do not bypass config validation.
- Do not bypass `SignalFrame` validation.
- Do not infer data coverage by scanning files when `DataCatalog` is available.
- Do not hard-code one data source into the broker or metrics layers.
- Keep user strategy code outside core engine modules.
````

- [ ] **Step 6: Commit docs**

Run:

```bash
git add README.md docs/architecture.md docs/data-ingestion.md docs/data-contracts.md docs/signal-integration.md docs/metrics-extension.md docs/reports.md docs/cli.md docs/ai-handoff.md
git commit -m "docs: add user and AI handoff guides"
```

Expected: commit succeeds.

## Task 14: Final Verification and MVP Readiness Pass

**Files:**

- Modify: files found by verification only when tests expose concrete defects

- [ ] **Step 1: Run full test suite**

Run:

```bash
pytest -v
```

Expected: PASS.

- [ ] **Step 2: Run CLI help**

Run:

```bash
backtest --help
backtest data --help
backtest validate --help
backtest backtest --help
```

Expected: each command exits with code 0 and prints help text.

- [ ] **Step 3: Validate plan/spec coverage**

Check that these spec requirements are implemented:

```text
Python package plus CLI
Daily bars first
Frequency-aware contracts
AkShare provider
Parquet bar cache
SQLite data catalog and crawl tasks
Custom stock pool
File and Python signals
SignalFrame validation
Next-open default execution
A share basic execution constraints
Built-in metrics
Custom metric registry
Structured output and HTML report
Documentation for users and future model sessions
```

Expected: every item maps to at least one test and one module.

- [ ] **Step 4: Commit final verification fixes if any files changed**

Run:

```bash
git status --short
```

Expected: no output.

If verification caused code changes, run:

```bash
git add -A
git commit -m "fix: complete MVP verification"
```

Expected: commit succeeds when there are changed files. If there are no changed files, no commit is needed.

## Self-Review

Spec coverage:

- Data ingestion, cache, catalog, and tasks are covered by Tasks 4, 5, 6, 12, and 13.
- Signal input and `SignalFrame` are covered by Tasks 2 and 7.
- Execution, costs, slippage, and A share constraints are covered by Task 8.
- Metrics and custom metric extension are covered by Task 9.
- Reports and GUI-ready files are covered by Task 10.
- CLI and validation are covered by Tasks 1, 11, and 12.
- Documentation and AI handoff are covered by Task 13.
- End-to-end execution and final checks are covered by Tasks 11 and 14.

Placeholder scan:

- This plan avoids placeholder markers and names concrete files, commands, tests, and public interfaces.

Type consistency:

- `Frequency`, `AdjustMode`, `ExecutionTiming`, `MetricResultKind`, `BarRequest`, `CatalogRecord`, `CrawlTaskRecord`, `MetricResult`, `BacktestConfig`, and `BrokerResult` are introduced before later tasks use them.
- `SignalFrame` and `BarFrame` validation functions are defined in Task 2 and reused by later modules.
