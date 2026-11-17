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
from datetime import UTC, datetime, timedelta
from itertools import islice
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import select

from sm_events.calendar import rrule
from sm_events.calendar.expand import instances, is_occurrence
from sm_events.calendar.times import Span, to_local
from sm_events.content import schedule
from sm_events.content.schedule import Schedule
from sm_events.core import constants
from sm_events.core.access.events import load_event
from sm_events.core.errors import OverridesOrphaned
from sm_events.models import Event, OccurrenceOverride
from sm_events.web.schemas.overrides import (
    PreviewIn,
    PreviewOccurrence,
    PreviewOut,
    override_out,
)

__all__ = ["dropped_note", "orphans", "preview", "settle_overrides"]


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


def _occurrence(start: datetime, end: datetime, plan: Schedule) -> PreviewOccurrence:
    first, last = to_local(Span(start, end), all_day=plan.all_day, timezone=plan.timezone)
    return PreviewOccurrence(start=start, end=end, start_local=first, end_local=last)


async def preview(db: Any, who: ResourcePrincipal, data: PreviewIn) -> PreviewOut:
    """The next ``count`` occurrences of ``data``'s schedule after ``data.after``
    (default: its start), and, given ``event_id``, the overrides that schedule
    would orphan. Without an event it is pure computation. An event the caller may
    not see is a 404, so this never confirms a draft exists."""
    event = None
    if data.event_id is not None:
        event, _rights = await load_event(db, who, data.event_id)
    plan = schedule.build(data.times, data.rrule)
    after = data.after or plan.span.starts_at
    if plan.rrule is None:
        single = [(plan.span.starts_at, plan.span.ends_at)] if plan.span.starts_at >= after else []
        found = single
    else:
        rule = rrule.parse(plan.rrule, all_day=plan.all_day, timezone=plan.timezone)
        horizon = plan.span.starts_at + timedelta(days=366 * constants.RRULE_MAX_YEARS)
        walk = instances(
            rule=rule,
            span=plan.span,
            all_day=plan.all_day,
            timezone=plan.timezone,
            window_start=after,
            window_end=horizon,
            recurrence_until=plan.recurrence_until,
        )
        found = [
            (i.start, i.end) for i in islice((i for i in walk if i.start >= after), data.count)
        ]
    dropped = await orphans(db, event, plan) if event is not None else []
    return PreviewOut(
        occurrences=[_occurrence(start, end, plan) for start, end in found[: data.count]],
        recurrence_until=plan.recurrence_until,
        orphaned=[override_out(r, all_day=plan.all_day, timezone=plan.timezone) for r in dropped],
    )
