"""Which occurrence of an event a public page shows.

An occurrence's address is ``{slug}?date=YYYY-MM-DD``: the local date of its original start in the
event's timezone (an all-day one: its first date). Rules are at most daily, so one local date
names at most one occurrence. A moved occurrence keeps its original date in the address and shows
its new time; a cancelled one is shown, marked; a skipped one, a date that is not an occurrence
and an unparsable date are the 404.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

__all__ = ["ShownOccurrence"]


@dataclass(frozen=True)
class ShownOccurrence:
    """One occurrence as a page shows it. ``end_date`` is exclusive, like the occurrences read's."""

    start: datetime
    end: datetime
    all_day: bool
    start_date: date | None
    end_date: date | None
    status: Literal["scheduled", "cancelled", "rescheduled"]
    previous_start: datetime | None
    date_param: date | None
