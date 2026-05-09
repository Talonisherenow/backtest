from datetime import date, datetime
from pathlib import Path

import pytest

from backtest.core.contracts import CatalogRecord
from backtest.core.enums import AdjustMode, Frequency
from backtest.data.jobs import (
    DataSyncJobConfig,
    MarketDataJobRunner,
    load_data_sync_job_config,
)


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
  - 1h
  - 4h
adjust: none
start_date: "2025-01-01"
end_date: "2025-01-31"
bars_root: data/crypto/bars
metadata: data/crypto/metadata.sqlite
output_dir: runs/crypto_market_data/bitget_core
page_delay_seconds: 0.25
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
    assert config.frequencies == [Frequency.DAILY, Frequency.HOUR_1, Frequency.HOUR_4]
    assert config.adjust == AdjustMode.NONE
    assert config.start_date == date(2025, 1, 1)
    assert config.end_date == date(2025, 1, 31)
    assert config.bars_root == Path("data/crypto/bars")
    assert config.metadata == Path("data/crypto/metadata.sqlite")
    assert config.output_dir == Path("runs/crypto_market_data/bitget_core")
    assert config.page_delay_seconds == 0.25
    assert config.retry.max_attempts == 5
    assert config.retry.request_delay_seconds == 0.5
    assert config.retry.failure_cooldown_seconds == 30
    assert config.retry.continue_on_error is True
    assert config.catalog_source == "ccxt:bitget"


def test_tracked_bitget_job_config_uses_exchange_scoped_cache_root():
    config = load_data_sync_job_config("configs/data_jobs/crypto_bitget_core.yaml")

    assert config.exchange == "bitget"
    assert Frequency.HOUR_1 in config.frequencies
    assert config.bars_root == Path("data/crypto/bitget/bars")
    assert config.metadata == Path("data/crypto/bitget/metadata.sqlite")
    assert config.page_delay_seconds > 0


def test_data_sync_job_config_accepts_legacy_sixty_minute_frequency(tmp_path: Path):
    job_path = _write_job_config(
        tmp_path,
        """
name: crypto-legacy-frequency
source: ccxt
exchange: bitget
symbols:
  - BTC/USDT
frequencies:
  - 60m
adjust: none
start_date: "2025-01-01"
end_date: "2025-01-02"
""",
    )

    config = load_data_sync_job_config(job_path)

    assert config.frequencies == [Frequency.HOUR_1]
    assert config.frequencies[0].value == "1h"


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
