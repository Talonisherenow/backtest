from datetime import date


def split_missing_ranges_to_tasks(
    missing_ranges: list[tuple[str, date, date]],
) -> list[tuple[str, date, date]]:
    return list(missing_ranges)
