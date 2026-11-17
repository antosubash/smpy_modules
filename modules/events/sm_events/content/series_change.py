"""What changing a series does to its overrides.

An override names one occurrence by its original start. When the rule, the start,
the timezone or the all-day flag changes, some of those instants may no longer be
occurrences: the override is **orphaned**. Orphans are never remapped (moving a
weekly 10:00 series to 11:00 orphans every override). A change that would orphan
any is refused (409 ``overrides_orphaned``) unless the caller says to drop them,
which deletes them in the same transaction and records them in the revision's note.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC
from typing import Any

from sqlalchemy import select

from sm_events.calendar import rrule
from sm_events.calendar.expand import is_occurrence
from sm_events.content.schedule import Schedule
from sm_events.core import constants
from sm_events.core.errors import OverridesOrphaned
from sm_events.models import Event, OccurrenceOverride

__all__ = ["dropped_note", "orphans", "settle_overrides"]


async def orphans(db: Any, event: Event, plan: Schedule) -> list[OccurrenceOverride]:
    """The event's overrides whose original start is not an occurrence of ``plan``
    (every override, when ``plan`` does not recur)."""
    rows = list(
        (
            await db.execute(
                select(OccurrenceOverride)
                .where(OccurrenceOverride.event_id == event.id)
                .order_by(OccurrenceOverride.original_start)
            )
        )
        .scalars()
        .all()
    )
    if not rows or plan.rrule is None:
        return rows
    rule = rrule.parse(plan.rrule, all_day=plan.all_day, timezone=plan.timezone)
    return [
        row
        for row in rows
        if not is_occurrence(
            row.original_start,
            rule=rule,
            span=plan.span,
            all_day=plan.all_day,
            timezone=plan.timezone,
            recurrence_until=plan.recurrence_until,
        )
    ]


async def settle_overrides(
    db: Any, event: Event, plan: Schedule, *, drop: bool
) -> list[OccurrenceOverride]:
    """Refuse (``OverridesOrphaned``) or, with ``drop``, delete the orphans; the
    ones deleted, for the revision's note."""
    found = await orphans(db, event, plan)
    if not found:
        return []
    if not drop:
        raise OverridesOrphaned
    for row in found:
        await db.delete(row)
    await db.flush()
    return found


def dropped_note(dropped: Sequence[OccurrenceOverride]) -> str | None:
    """``dropped overrides: <original starts>``, cut to the note's bound."""
    if not dropped:
        return None
    stamps = [row.original_start.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ") for row in dropped]
    text = "dropped overrides: " + ", ".join(stamps)
    if len(text) <= constants.NOTE_MAX:
        return text
    return text[: constants.NOTE_MAX - 1].rstrip(", ") + "…"
