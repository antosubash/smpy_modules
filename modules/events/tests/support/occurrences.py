"""Helpers for the occurrences read's tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sm_events.calendar.occurrence import OccurrenceFilters
from sm_events.calendar.occurrences import occurrences

from tests.support.access import principal

OWNER = principal("o", "events.view", "events.edit", "events.publish")
ALL = OccurrenceFilters()


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


async def read(db: Any, who, start, end, filters=ALL, locale="en"):
    return await occurrences(
        db,
        tenant_id="default",
        viewer=who,
        start=start,
        end=end,
        filters=filters,
        default_locale=locale,
    )
