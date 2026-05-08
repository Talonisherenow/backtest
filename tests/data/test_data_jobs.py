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
