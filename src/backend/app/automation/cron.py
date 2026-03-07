from __future__ import annotations

from datetime import datetime, timedelta, timezone


def next_cron_time(cron_expression: str, *, after: datetime | None = None) -> datetime:
    fields = _parse_cron_expression(cron_expression)
    current = (after or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(second=0, microsecond=0)
    candidate = current + timedelta(minutes=1)

    for _ in range(0, 60 * 24 * 366):
        if _matches(candidate, fields):
            return candidate
        candidate += timedelta(minutes=1)

    raise ValueError(f"unable to compute next cron time for: {cron_expression}")


def _parse_cron_expression(expression: str) -> tuple[set[int], set[int], set[int], set[int], set[int]]:
    parts = [item.strip() for item in str(expression or "").split() if item.strip()]
    if len(parts) != 5:
        raise ValueError("cron expression must have exactly 5 fields")

    minute = _parse_field(parts[0], 0, 59)
    hour = _parse_field(parts[1], 0, 23)
    day = _parse_field(parts[2], 1, 31)
    month = _parse_field(parts[3], 1, 12)
    weekday = _parse_field(parts[4], 0, 6, sunday_alias=True)
    return minute, hour, day, month, weekday


def _parse_field(field: str, minimum: int, maximum: int, *, sunday_alias: bool = False) -> set[int]:
    if field == "*":
        return set(range(minimum, maximum + 1))

    results: set[int] = set()
    for chunk in field.split(","):
        value = chunk.strip()
        if not value:
            continue

        if value.startswith("*/"):
            step = int(value[2:])
            if step <= 0:
                raise ValueError(f"invalid cron step: {field}")
            results.update(range(minimum, maximum + 1, step))
            continue

        parsed = int(value)
        if sunday_alias and parsed == 7:
            parsed = 0
        if parsed < minimum or parsed > maximum:
            raise ValueError(f"cron value out of range: {field}")
        results.add(parsed)

    if not results:
        raise ValueError(f"empty cron field: {field}")
    return results


def _matches(candidate: datetime, fields: tuple[set[int], set[int], set[int], set[int], set[int]]) -> bool:
    minute, hour, day, month, weekday = fields
    return (
        candidate.minute in minute
        and candidate.hour in hour
        and candidate.day in day
        and candidate.month in month
        and candidate.weekday() in weekday
    )
