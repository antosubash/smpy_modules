"""``GET /api/events/events/{id}/registrations``: how many seats are taken at each occurrence.

For the editor of the event, so it needs the right to **write** the event: anyone else (a viewer
included) gets the 404 a missing event gets. It returns counts and times, never who holds a seat:
that is the registration provider's own data behind its own grants.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from sm_events.calendar.times import Span, to_local
from sm_events.core.access.events import load_event
from sm_events.core.clock import utcnow
from sm_events.core.errors import NotFound
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Event, OccurrenceOverride
from sm_events.registration.occurrence import original_start_of, resolve_key
from sm_events.registration.seat_reads import counts
from sm_events.web.endpoints.deps import Principal, event_db, require_view
from sm_events.web.schemas.registration import RegistrationCountOut, RegistrationCountsOut

router = APIRouter(prefix="/events", tags=["events"], dependencies=[require_view])


async def _overrides(db: Any, event: Event, keys: list[str]) -> list[OccurrenceOverride]:
    originals = {o for key in keys if (o := original_start_of(event, key)) is not None}
    if event.rrule is None or not originals:
        return []
    stmt = select(OccurrenceOverride).where(
        OccurrenceOverride.event_id == event.id,
        OccurrenceOverride.original_start.in_(originals),  # type: ignore[attr-defined]
    )
    return list((await db.execute(stmt)).scalars().all())


def _item(event: Event, changes: list[OccurrenceOverride], key: str, taken: int) -> Any:
    occurrence = resolve_key(event, changes, key)
    start = local = None
    if occurrence is not None:
        start = occurrence.start
        local = to_local(
            Span(occurrence.start, occurrence.end), all_day=event.all_day, timezone=event.timezone
        )[0]
    return RegistrationCountOut(
        occurrence_key=key,
        start=start,
        start_local=local,
        taken=taken,
        capacity=event.registration_capacity,
    )


def _order(item: RegistrationCountOut, now: datetime) -> tuple[int, float]:
    """Upcoming first (soonest first), then the past (latest first), then what has no time."""
    if item.start is None:
        return (2, 0.0)
    stamp = item.start.timestamp()
    return (0, stamp) if item.start >= now else (1, -stamp)


@router.get("/{event_id}/registrations")
async def registration_counts(
    event_id: uuid.UUID, who: Principal, db=Depends(event_db)
) -> RegistrationCountsOut:
    event, rights = await load_event(db, who, event_id)
    if not rights.write:
        raise NotFound
    taken = await counts(db, tenant_id=bound_tenant(), event_id=event.id)
    changes = await _overrides(db, event, [key for key, _ in taken])
    now = utcnow()
    items = sorted(
        (_item(event, changes, key, n) for key, n in taken), key=lambda item: _order(item, now)
    )
    return RegistrationCountsOut(items=items, total=len(items))
