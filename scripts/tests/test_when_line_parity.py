"""The reminder mail and the newsletter event card word an event's date and time the same.

Two formatters, in two modules that may not import each other (``sm_events.reminders.formatting``
and ``sm_newsletter.content.render.event_card``), run through ONE case table. The only allowed
difference is the reminder's own "(all day)" wording around an all-day date."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest
from sm_events.reminders.formatting import format_when
from sm_newsletter.content.render.event_card import when


@dataclass
class Case:
    starts_at: datetime
    ends_at: datetime
    timezone: str
    all_day: bool = False
    start_date: date | None = None
    end_date: date | None = None


def _utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


CASES = {
    "one day": Case(_utc(2027, 3, 10, 9), _utc(2027, 3, 10, 11, 30), "Europe/Vienna"),
    "afternoon, new york": Case(_utc(2027, 7, 1, 18), _utc(2027, 7, 1, 20), "America/New_York"),
    "across midnight": Case(_utc(2027, 3, 10, 22), _utc(2027, 3, 11, 2), "Europe/Vienna"),
    "across the spring change": Case(
        _utc(2027, 3, 28, 0, 30), _utc(2027, 3, 28, 3, 30), "Europe/Vienna"
    ),
    "lord howe, half hour zone": Case(
        _utc(2027, 1, 5, 1), _utc(2027, 1, 5, 2, 30), "Australia/Lord_Howe"
    ),
    "all day": Case(
        _utc(2027, 3, 20),
        _utc(2027, 3, 21),
        "Europe/Vienna",
        True,
        date(2027, 3, 20),
        date(2027, 3, 21),
    ),
    "all day, three days": Case(
        _utc(2027, 3, 20),
        _utc(2027, 3, 23),
        "Europe/Vienna",
        True,
        date(2027, 3, 20),
        date(2027, 3, 23),
    ),
}


def _reminder(case: Case, locale: str) -> str:
    if case.all_day:
        # The reminder's all-day instants are the zone's midnights; the card carries dates.
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(case.timezone)
        start = datetime.combine(case.start_date, datetime.min.time(), zone)
        end = datetime.combine(case.end_date, datetime.min.time(), zone)
    else:
        start, end = case.starts_at, case.ends_at
    return format_when(
        start=start, end=end, all_day=case.all_day, timezone=case.timezone, locale=locale
    )


@pytest.mark.parametrize("locale", ["en", "de"])
@pytest.mark.parametrize("name", sorted(CASES))
def test_both_formatters_produce_the_same_text(name: str, locale: str) -> None:
    case = CASES[name]
    mine = _reminder(case, locale)
    if case.all_day:
        mine = mine.removesuffix(" (all day)").removesuffix(" (ganztägig)")
    assert mine == when(case, locale)
