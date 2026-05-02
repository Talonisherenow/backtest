from datetime import date

from backtest.data.coverage import split_missing_ranges_to_tasks


def test_split_missing_ranges_keeps_one_task_per_symbol_range():
    missing = [
        ("000001.SZ", date(2025, 1, 1), date(2025, 1, 5)),
        ("600519.SH", date(2025, 1, 1), date(2025, 1, 5)),
    ]

    tasks = split_missing_ranges_to_tasks(missing)

    assert tasks == missing
