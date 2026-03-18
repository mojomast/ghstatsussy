from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone


TIME_RANGE_RE = re.compile(r"^\s*(\d+)\s*([dwmy])\s*$", re.IGNORECASE)


@dataclass(slots=True)
class TimeWindow:
    since_spec: str
    start_at: datetime
    end_at: datetime
    label: str

    @property
    def days(self) -> int:
        return (self.end_at.date() - self.start_at.date()).days + 1

    @property
    def start_date(self) -> date:
        return self.start_at.date()

    @property
    def end_date(self) -> date:
        return self.end_at.date()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_since_spec(value: str) -> timedelta:
    match = TIME_RANGE_RE.match(value)
    if not match:
        raise ValueError(
            "Invalid time window. Use values like 7d, 30d, 12w, 6m, or 1y."
        )

    amount = int(match.group(1))
    unit = match.group(2).lower()
    if amount <= 0:
        raise ValueError("Time window must be greater than zero.")

    days_per_unit = {
        "d": 1,
        "w": 7,
        "m": 30,
        "y": 365,
    }
    return timedelta(days=amount * days_per_unit[unit])


def build_time_window(since: str, *, now: datetime | None = None) -> TimeWindow:
    current = now or utc_now()
    delta = parse_since_spec(since)
    start = current - delta + timedelta(days=1)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = current.replace(microsecond=0)
    return TimeWindow(
        since_spec=since,
        start_at=start,
        end_at=end,
        label=f"Last {since.lower()}",
    )


def parse_github_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iter_dates(start: date, end: date) -> list[date]:
    span = (end - start).days
    return [start + timedelta(days=offset) for offset in range(span + 1)]
