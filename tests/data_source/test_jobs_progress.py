from datetime import datetime

from backtest.core.enums import AdjustMode, Frequency
from backtest.data.jobs import JobItemResult, JobResult
from backtest.data_source.jobs import DataSourceJobRegistry, _planned_item_count


def test_planned_item_count_from_dict_payload():
    config = {
        "name": "demo",
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "frequencies": ["1h", "4h"],
    }
    assert _planned_item_count(config) == 4


def test_inline_submit_updates_progress_after_each_item():
    observed = []

    def run_job(config, on_item_finished=None):
        result = JobResult(
            name=config["name"],
            started_at=datetime(2025, 1, 1, 9, 0, 1),
            finished_at=datetime(2025, 1, 1, 9, 0, 3),
        )
        items = [
            JobItemResult(
                job_name=config["name"],
                source="ccxt:bitget",
                exchange="bitget",
                symbol="BTCUSDT",
                frequency=Frequency.HOUR_1,
                adjust=AdjustMode.NONE,
                start_date=datetime(2025, 1, 1).date(),
                end_date=datetime(2025, 1, 2).date(),
                status="success",
                attempts=1,
                started_at=datetime(2025, 1, 1, 9, 0, 1),
                finished_at=datetime(2025, 1, 1, 9, 0, 2),
            ),
            JobItemResult(
                job_name=config["name"],
                source="ccxt:bitget",
                exchange="bitget",
                symbol="ETHUSDT",
                frequency=Frequency.HOUR_1,
                adjust=AdjustMode.NONE,
                start_date=datetime(2025, 1, 1).date(),
                end_date=datetime(2025, 1, 2).date(),
                status="failed",
                attempts=1,
                started_at=datetime(2025, 1, 1, 9, 0, 2),
                finished_at=datetime(2025, 1, 1, 9, 0, 3),
            ),
        ]
        for item in items:
            result.items.append(item)
            if on_item_finished is not None:
                on_item_finished(item)
                observed.append(
                    {
                        "success": sum(1 for entry in result.items if entry.status == "success"),
                        "failed": sum(1 for entry in result.items if entry.status == "failed"),
                    }
                )
        return result

    registry = DataSourceJobRegistry(
        run_job,
        now=lambda: datetime(2025, 1, 1, 9, 0, 0),
        run_inline=True,
    )
    snapshot = registry.submit(
        {
            "name": "Progress Job",
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "frequencies": ["1h"],
        }
    )

    assert snapshot.status == "failed"
    assert snapshot.total_items == 2
    assert snapshot.success_count == 1
    assert snapshot.failed_count == 1
    assert observed == [{"success": 1, "failed": 0}, {"success": 1, "failed": 1}]
