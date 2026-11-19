"""Render events with the caller's rights and the local wall clock.

Everything here reads; a write refreshes its event first (an ``UPDATE`` leaves the
database-stamped columns unloaded, and an async session cannot load them lazily).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import select

from sm_events.calendar.plugins import registry
from sm_events.calendar.times import Span, to_local
from sm_events.content.texts import texts_of
from sm_events.core import constants
from sm_events.core.access.events import is_locked, visible_events
from sm_events.core.access.rights import CalendarRights, calendar_rights_many
from sm_events.models import Calendar, Event, EventText, OccurrenceOverride
from sm_events.web.schemas.events_out import EventListItem, EventOut, SubEvent
from sm_events.web.schemas.overrides import override_out
from sm_events.web.schemas.texts import TextOut

__all__ = ["render", "render_items"]

SUB_EVENTS_SHOWN = 200


def _local(event: Event) -> tuple[str, str]:
    return to_local(
        Span(event.starts_at, event.ends_at), all_day=event.all_day, timezone=event.timezone
    )


def _base(event: Event, rights: CalendarRights | None) -> dict[str, Any]:
    start, end = _local(event)
    return {
        "id": event.id,
        "calendar_id": event.calendar_id,
        "parent_id": event.parent_id,
        "type": event.type,
        "type_installed": (etype := registry.get_type(event.type)) is not None,
        "type_label_key": etype.label_key if etype is not None else None,
        "status": event.status,
        "scheduled": event.publish_at is not None,
        "cancelled": event.cancelled,
        "all_day": event.all_day,
        "timezone": event.timezone,
        "starts_at": event.starts_at,
        "ends_at": event.ends_at,
        "start_local": start,
        "end_local": end,
        "rrule": event.rrule,
        "category_id": event.category_id,
        "venue_name": event.venue_name,
        "revision": event.revision,
        "publish_at": event.publish_at,
        "published_at": event.published_at,
        "trashed": event.is_deleted,
        "can_write": bool(rights and rights.write_events),
        "can_publish": bool(rights and rights.publish),
        "locked": is_locked(event),
    }


def pick_title(texts: dict[str, EventText], *locales: str | None) -> tuple[str, str]:
    """The title in the first of ``locales`` the event has, else the first by locale."""
    for locale in locales:
        if locale is not None and locale in texts:
            return texts[locale].title, locale
    if not texts:
        return "", ""
    first = min(texts)
    return texts[first].title, first


async def _rights(
    db: Any, who: ResourcePrincipal, events: Sequence[Event]
) -> dict[uuid.UUID, CalendarRights]:
    ids = {e.calendar_id for e in events}
    if not ids:
        return {}
    calendars = (
        (await db.execute(select(Calendar).where(Calendar.id.in_(ids)))).scalars().all()  # type: ignore[attr-defined]
    )
    return await calendar_rights_many(db, who, calendars)


async def render_items(
    db: Any,
    who: ResourcePrincipal,
    events: Sequence[Event],
    *,
    locale: str | None,
    default_locale: str,
) -> list[EventListItem]:
    rights = await _rights(db, who, events)
    texts = await texts_of(db, [e.id for e in events])
    out: list[EventListItem] = []
    for event in events:
        title, lang = pick_title(texts[event.id], locale, default_locale)
        out.append(
            EventListItem(**_base(event, rights.get(event.calendar_id)), title=title, lang=lang)
        )
    return out


async def _sub_events(
    db: Any, who: ResourcePrincipal, event: Event, locale: str | None, default_locale: str
) -> list[SubEvent]:
    stmt = (
        visible_events(who)
        .where(Event.parent_id == event.id)
        .order_by(Event.starts_at, Event.id)
        .limit(SUB_EVENTS_SHOWN)
    )
    kids = list((await db.execute(stmt)).scalars().all())
    texts = await texts_of(db, [k.id for k in kids])
    return [
        SubEvent(
            id=kid.id,
            title=pick_title(texts[kid.id], locale, default_locale)[0],
            start_local=_local(kid)[0],
        )
        for kid in kids
    ]


async def render(
    db: Any,
    who: ResourcePrincipal,
    event: Event,
    *,
    locale: str | None,
    default_locale: str,
) -> EventOut:
    """The full event. A caller who may not write it gets no override notes."""
    rights = (await _rights(db, who, [event])).get(event.calendar_id)
    texts = (await texts_of(db, [event.id]))[event.id]
    found = (
        await db.execute(
            select(OccurrenceOverride)
            .where(OccurrenceOverride.event_id == event.id)
            .order_by(OccurrenceOverride.original_start)
            .limit(constants.MAX_OCCURRENCES)
        )
    ).scalars()
    can_write = bool(rights and rights.write_events)
    overrides = [override_out(o, all_day=event.all_day, timezone=event.timezone) for o in found]
    if not can_write:
        overrides = [o.model_copy(update={"note": None}) for o in overrides]
    publish_local = None
    if event.publish_at is not None:
        publish_local = to_local(
            Span(event.publish_at, event.publish_at), all_day=False, timezone=event.timezone
        )[0]
    return EventOut(
        **_base(event, rights),
        uid=event.uid,
        recurrence_until=event.recurrence_until,
        publish_at_local=publish_local,
        attendance_mode=event.attendance_mode,
        address=event.address,
        online_url=event.online_url,
        latitude=event.latitude,
        longitude=event.longitude,
        organiser=event.organiser,
        image=event.image,
        registration_url=event.registration_url,
        extra=event.extra,
        created_at=event.created_at,
        updated_at=event.updated_at,
        texts={locale_: TextOut.model_validate(t) for locale_, t in texts.items()},
        overrides=overrides,
        sub_events=await _sub_events(db, who, event, locale, default_locale),
    )
