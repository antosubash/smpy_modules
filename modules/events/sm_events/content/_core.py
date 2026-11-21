"""The write path's bodies below the rights check: internal to events.

:func:`create_core` and :func:`apply_patch` are what ``create_event`` and ``update_event`` (in
:mod:`sm_events.content.events_write`) do once the caller's rights are settled. The import (a
worker with no session, whose rights are the stored grants and fresh per-item checks) calls them
directly, and nothing else may: a new caller would skip the rights check. A test pins the two
importers.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sm_events.calendar.plugins import registry
from sm_events.content import bus, notices, revisions, schedule
from sm_events.content.fields import check_category, check_parent, has_live_children
from sm_events.content.guard import Unchanged, claim
from sm_events.content.series_change import dropped_note, settle_overrides
from sm_events.content.texts import apply_texts
from sm_events.content.types import validate_extra
from sm_events.core import constants
from sm_events.core.errors import InvalidParent, UnknownType
from sm_events.core.errors_extensions import TypeNotInstalled
from sm_events.models import Calendar, Event
from sm_events.models.enums import EventStatus
from sm_events.web.schemas.events_in import EventCreate, EventPatch

__all__ = ["SCALARS", "apply_patch", "create_core"]

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
        extra=extra,
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
        specific = [notices.series_changed(event, old)]
        if event.cancelled and not was_cancelled:
            specific.append(notices.cancelled(event, original_start=None))
        elif was_cancelled and not event.cancelled:
            specific.append(notices.reinstated(event, original_start=None))
        bus.emit(db, *specific)
        if not any(specific):  # a write a specific event covers announces only that one
            bus.emit(db, notices.updated(event, names))
