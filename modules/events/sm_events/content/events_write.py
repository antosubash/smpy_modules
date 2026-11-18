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
from typing import Any

from simple_module_core.resources import ResourcePrincipal

from sm_events.calendar import registry
from sm_events.content import bus, notices, revisions, schedule
from sm_events.content.fields import check_category, check_parent, has_live_children
from sm_events.content.guard import Unchanged, claim
from sm_events.content.series_change import dropped_note, settle_overrides
from sm_events.content.texts import apply_texts
from sm_events.content.types import validate_extra
from sm_events.core import constants
from sm_events.core.access.events import load_event, require
from sm_events.core.access.rights import writable_calendar
from sm_events.core.errors import InvalidParent, UnknownType
from sm_events.core.errors_extensions import TypeNotInstalled
from sm_events.models import Event
from sm_events.models.enums import EventStatus
from sm_events.web.schemas.events_in import EventCreate, EventPatch

__all__ = ["create_event", "update_event"]

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
    if registry.get_type(data.type) is None:
        raise UnknownType
    extra = validate_extra(data.type, data.extra)
    plan = schedule.build(data.times, data.rrule)
    await check_category(db, data.category_id)
    if data.parent_id is not None:
        if plan.recurring:
            raise InvalidParent  # a sub-event cannot recur
        await check_parent(db, calendar.id, data.parent_id)
    event = Event(
        calendar_id=calendar.id,
        parent_id=data.parent_id,
        uid=f"{uuid.uuid4()}{constants.UID_SUFFIX}",
        type=data.type,
        status=EventStatus.DRAFT.value,
        all_day=plan.all_day,
        starts_at=plan.span.starts_at,
        ends_at=plan.span.ends_at,
        timezone=plan.timezone,
        rrule=plan.rrule,
        recurrence_until=plan.recurrence_until,
        revision=1,
        extra=extra,
        **{name: getattr(data, name) for name in SCALARS},
    )
    async with db.begin_nested():  # a failed text leaves no half-created event
        db.add(event)
        await db.flush()
        await apply_texts(db, event, data.texts, locales=locales, creating=True)
        await revisions.record(db, event, action="created", actor=who.user_id)
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
        await _apply(db, who, event, data, locales)
    except Unchanged:
        await db.refresh(event)  # the savepoint rolled back: the stored revision
    return event


def _apply_extra(event: Event, extra: dict[str, Any]) -> bool:
    """Replace ``extra`` whole, validated against the event's type. An event whose type is not
    installed keeps its stored ``extra`` untouched, and refuses a change to it."""
    if registry.get_type(event.type) is None:
        raise TypeNotInstalled
    new = validate_extra(event.type, extra)
    if new == event.extra:
        return False
    event.extra = new
    return True


async def _apply(
    db: Any, who: ResourcePrincipal, event: Event, data: EventPatch, locales: tuple[str, ...]
) -> None:
    sent = data.model_fields_set
    async with db.begin_nested():
        await claim(db, event, data.expected_revision, actor=who.user_id)
        old = schedule.of_event(event)
        was_cancelled = event.cancelled
        dropped: list = []
        changed = False
        names: set[str] = set()  # what changed, for ``EventUpdated``
        if "category_id" in sent:
            await check_category(db, data.category_id)
        if sent & {"times", "rrule"}:
            plan = schedule.patched(
                event, times=data.times, rule=data.rrule, rule_set="rrule" in sent
            )
            if plan != old:
                changed = True
                names.add("times" if "times" in sent else "rrule")
                await _check_recurrence(db, event, plan)
                dropped = await settle_overrides(db, event, plan, drop=data.drop_orphaned_overrides)
                event.starts_at, event.ends_at = plan.span.starts_at, plan.span.ends_at
                event.timezone, event.all_day = plan.timezone, plan.all_day
                event.rrule, event.recurrence_until = plan.rrule, plan.recurrence_until
        for name in SCALARS:
            if name in sent and getattr(event, name) != getattr(data, name):
                setattr(event, name, getattr(data, name))
                changed = True
                names.add(name)
        if data.texts is not None and await apply_texts(
            db, event, data.texts, locales=locales, creating=False
        ):
            changed = True
            names.add("texts")
        if "extra" in sent and data.extra is not None and _apply_extra(event, data.extra):
            changed = True
            names.add("extra")
        if not changed:
            raise Unchanged
        await db.flush()
        await revisions.record(
            db, event, action="updated", actor=who.user_id, note=dropped_note(dropped)
        )
        specific = [notices.series_changed(event, old)]
        if event.cancelled and not was_cancelled:
            specific.append(notices.cancelled(event, original_start=None))
        elif was_cancelled and not event.cancelled:
            specific.append(notices.reinstated(event, original_start=None))
        bus.emit(db, *specific)
        if not any(specific):  # a write a specific event covers announces only that one
            bus.emit(db, notices.updated(event, names))
