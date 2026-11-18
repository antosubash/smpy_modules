"""Create and update events. No FastAPI, no commit: the request finishes the
transaction (:func:`sm_events.content.bus.commit`) and so publishes what a write
queued.

* **Rights.** Creating needs ``write_events`` on the calendar (404 when the calendar
  is not visible, 403 when it is but not writable). Changing an event needs the same
  on its calendar, plus ``events.publish`` when the event is published or scheduled
  (:func:`sm_events.core.access.events.require`).
* **The stale guard comes first.** Every write opens a savepoint and its first
  statement is the compare-and-set on ``revision``; any failure after it rolls the
  savepoint back, so a refused write leaves no revision bump and no history row,
  and the request's transaction is never aborted.
* **Recurrence and sub-events exclude each other**, and neither the calendar nor
  the parent can change after create.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from simple_module_core.resources import ResourcePrincipal

from sm_events.content import bus, notices, revisions, schedule
from sm_events.content.fields import check_category, check_parent, has_live_children
from sm_events.content.guard import Unchanged, claim
from sm_events.content.series_change import dropped_note, settle_overrides
from sm_events.content.texts import apply_texts
from sm_events.core import constants
from sm_events.core.access.events import load_event, require
from sm_events.core.access.rights import writable_calendar
from sm_events.core.errors import InvalidParent, UnknownType
from sm_events.models import Calendar, Event
from sm_events.models.enums import DEFAULT_EVENT_TYPE, EventStatus
from sm_events.web.schemas.events_in import EventCreate, EventPatch

__all__ = ["apply_patch", "create_core", "create_event", "update_event"]

SCALARS = (
    "cancelled",
    "attendance_mode",
    "venue_name",
    "address",
    "online_url",
    "latitude",
    "longitude",
    "category_id",
    "organiser",
    "image",
    "registration_url",
)


async def create_event(
    db: Any, who: ResourcePrincipal, data: EventCreate, *, locales: tuple[str, ...]
) -> Event:
    """A new draft at revision 1, with its texts and a ``created`` history row."""
    calendar = await writable_calendar(db, who, data.calendar_id)
    return await create_core(db, calendar, data, actor=who.user_id, locales=locales)


async def create_core(
    db: Any,
    calendar: Calendar,
    data: EventCreate,
    *,
    actor: str | None,
    locales: tuple[str, ...],
    uid: str | None = None,
    status: str = EventStatus.DRAFT.value,
    published_at: datetime | None = None,
    note: str | None = None,
    before_history: Callable[[Event], Awaitable[None]] | None = None,
) -> Event:
    """Everything :func:`create_event` does after the rights check. The import calls it with
    its own ``uid`` (a file's), ``status`` and ``published_at`` and a history ``note``; a
    request leaves them at their defaults (a fresh UID, a draft)."""
    if data.type != DEFAULT_EVENT_TYPE:
        raise UnknownType
    plan = schedule.build(data.times, data.rrule)
    await check_category(db, data.category_id)
    if data.parent_id is not None:
        if plan.recurring:
            raise InvalidParent  # a sub-event cannot recur
        await check_parent(db, calendar.id, data.parent_id)
    event = Event(
        calendar_id=calendar.id,
        parent_id=data.parent_id,
        uid=uid or f"{uuid.uuid4()}{constants.UID_SUFFIX}",
        type=data.type,
        status=status,
        published_at=published_at,
        all_day=plan.all_day,
        starts_at=plan.span.starts_at,
        ends_at=plan.span.ends_at,
        timezone=plan.timezone,
        rrule=plan.rrule,
        recurrence_until=plan.recurrence_until,
        revision=1,
        extra={},
        **{name: getattr(data, name) for name in SCALARS},
    )
    async with db.begin_nested():  # a failed text leaves no half-created event
        db.add(event)
        await db.flush()
        await apply_texts(db, event, data.texts, locales=locales, creating=True)
        if before_history is not None:
            await before_history(event)
        await revisions.record(db, event, action="created", actor=actor, note=note)
    return event


async def _check_recurrence(db: Any, event: Event, plan: schedule.Schedule) -> None:
    """A recurring event has no parent and no live sub-events."""
    if plan.recurring and (event.parent_id is not None or await has_live_children(db, event.id)):
        raise InvalidParent


async def update_event(
    db: Any,
    who: ResourcePrincipal,
    event_id: uuid.UUID,
    data: EventPatch,
    *,
    locales: tuple[str, ...],
) -> Event:
    """Apply a PATCH: only the fields the body set. One that changes nothing (only
    ``expected_revision``, or values equal to the stored ones) writes nothing: same
    revision, no history row, no bus event, and the unchanged event comes back."""
    event, rights = await load_event(db, who, event_id)
    require(rights)
    try:
        await apply_patch(db, who.user_id, event, data, locales)
    except Unchanged:
        await db.refresh(event)  # the savepoint rolled back: the stored revision
    return event


async def apply_patch(
    db: Any,
    actor: str | None,
    event: Event,
    data: EventPatch,
    locales: tuple[str, ...],
    *,
    note: str | None = None,
    after: Callable[[Event], Awaitable[bool]] | None = None,
) -> None:
    """Everything :func:`update_event` does after the rights check. Raises :class:`Unchanged`
    (the savepoint rolled back) when nothing changes. ``note`` is added to the history row,
    and ``after`` runs inside the savepoint once the fields and texts are applied and answers
    whether *it* changed something (the import replaces the overrides there)."""
    sent = data.model_fields_set
    async with db.begin_nested():
        await claim(db, event, data.expected_revision, actor=actor)
        old = schedule.of_event(event)
        was_cancelled = event.cancelled
        dropped: list = []
        changed = False
        if "category_id" in sent:
            await check_category(db, data.category_id)
        if sent & {"times", "rrule"}:
            plan = schedule.patched(
                event, times=data.times, rule=data.rrule, rule_set="rrule" in sent
            )
            if plan != old:
                changed = True
                await _check_recurrence(db, event, plan)
                dropped = await settle_overrides(db, event, plan, drop=data.drop_orphaned_overrides)
                event.starts_at, event.ends_at = plan.span.starts_at, plan.span.ends_at
                event.timezone, event.all_day = plan.timezone, plan.all_day
                event.rrule, event.recurrence_until = plan.rrule, plan.recurrence_until
        for name in SCALARS:
            if name in sent and getattr(event, name) != getattr(data, name):
                setattr(event, name, getattr(data, name))
                changed = True
        if data.texts is not None and await apply_texts(
            db, event, data.texts, locales=locales, creating=False
        ):
            changed = True
        if after is not None and await after(event):
            changed = True
        if not changed:
            raise Unchanged
        await db.flush()
        notes = [n for n in (note, dropped_note(dropped)) if n]
        await revisions.record(
            db,
            event,
            action="updated",
            actor=actor,
            note="; ".join(notes)[: constants.NOTE_MAX] or None,
        )
        bus.emit(db, notices.series_changed(event, old))
        if event.cancelled and not was_cancelled:
            bus.emit(db, notices.cancelled(event, original_start=None))
