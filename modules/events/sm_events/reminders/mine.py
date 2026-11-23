"""\"My reminders\": the caller's own follows on events they can see now.

A follow on an event the caller can no longer see (unpublished, trashed, a share removed) is
listed as an opaque row (the follow's own id and nothing else): its title, calendar and time are
not theirs to read any more, but it counts toward their cap and they must be able to remove
it. Only the caller's own rows are read; nothing here shows who else follows anything.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import case, func, select

from sm_events.core import constants
from sm_events.core.access.events import visible_events
from sm_events.core.constants.reminders_limits import MINE_PAGE_MAX
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import bound_tenant
from sm_events.core.user_ids import canonical_user_id
from sm_events.models import Calendar, Event, EventFollow, EventText
from sm_events.reminders import candidates
from sm_events.web.services.events_out import pick_title

__all__ = ["MineCalendar", "MineItem", "MinePage", "my_reminders"]

_F = EventFollow.__table__


@dataclass(frozen=True)
class MineCalendar:
    id: uuid.UUID
    name: str
    color: str


@dataclass(frozen=True)
class MineItem:
    follow_id: uuid.UUID
    """The handle of one of the caller's own follows on this event: what Remove takes."""
    hidden: bool = False
    """An event the caller can no longer see. Everything below is then empty: the row says only
    that a follow exists, never what it was about."""
    event_id: uuid.UUID | None = None
    title: str | None = None
    lang: str | None = None
    calendar: MineCalendar | None = None
    leads: tuple[int, ...] = ()
    next_start: datetime | None = None


@dataclass(frozen=True)
class MinePage:
    items: list[MineItem]
    total: int
    """Every event the caller follows, visible or not (the cap counts them all)."""
    hidden: int
    """How many of those they can no longer see; each is listed as an opaque row, after the
    visible ones."""
    page: int
    page_size: int


async def my_reminders(
    db: Any,
    who: ResourcePrincipal,
    *,
    locale: str,
    page: int,
    page_size: int,
    settings: EventsSettings,
    now: datetime,
) -> MinePage:
    page = max(1, page)
    page_size = min(max(1, page_size), MINE_PAGE_MAX)
    if who.user_id is None or not who.has(constants.PERM_VIEW):
        return MinePage([], 0, 0, page, page_size)
    user_id = canonical_user_id(who.user_id)
    mine = (_F.c.tenant_id == bound_tenant(), _F.c.user_id == user_id)
    visible = visible_events(who, include_unpublished=False).with_only_columns(Event.id)
    is_visible = _F.c.event_id.in_(visible)

    followed = (
        await db.execute(select(func.count(func.distinct(_F.c.event_id))).where(*mine))
    ).scalar_one()
    seen = (
        await db.execute(select(func.count(func.distinct(_F.c.event_id))).where(*mine, is_visible))
    ).scalar_one()
    order = case((is_visible, 0), else_=1)
    page_rows = (
        await db.execute(
            select(_F.c.event_id, order.label("hidden"))
            .where(*mine)
            .group_by(_F.c.event_id)
            .order_by(order, func.min(_F.c.created_at).desc(), _F.c.event_id)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).all()
    items = await _items(db, user_id, page_rows, locale=locale, settings=settings, now=now)
    return MinePage(items, int(followed), int(followed - seen), page, page_size)


async def _items(
    db: Any,
    user_id: str,
    page_rows: list[Any],
    *,
    locale: str,
    settings: EventsSettings,
    now: datetime,
) -> list[MineItem]:
    if not page_rows:
        return []
    ids = [row[0] for row in page_rows]
    leads: dict[uuid.UUID, list[int]] = {}
    handle: dict[uuid.UUID, uuid.UUID] = {}
    for follow_id, event_id, lead in await db.execute(
        select(_F.c.id, _F.c.event_id, _F.c.lead_minutes)
        .where(_F.c.tenant_id == bound_tenant(), _F.c.user_id == user_id, _F.c.event_id.in_(ids))
        .order_by(_F.c.created_at, _F.c.lead_minutes)
    ):
        leads.setdefault(event_id, []).append(lead)
        handle.setdefault(event_id, follow_id)
    shown = [row[0] for row in page_rows if not row[1]]
    events, calendars, texts, upcoming = {}, {}, {}, {}
    if shown:
        events = {
            e.id: e
            for e in (await db.execute(select(Event).where(Event.id.in_(shown)))).scalars()  # type: ignore[attr-defined]
        }
        calendars = {
            c.id: c
            for c in (
                await db.execute(
                    select(Calendar).where(
                        Calendar.id.in_({e.calendar_id for e in events.values()})  # type: ignore[attr-defined]
                    )
                )
            ).scalars()
        }
        for text in (
            await db.execute(select(EventText).where(EventText.event_id.in_(shown)))  # type: ignore[attr-defined]
        ).scalars():
            texts.setdefault(text.event_id, {})[text.locale] = text
        upcoming = await candidates.next_starts(db, list(events.values()), now=now)
    default = settings.content_locales[0] if settings.content_locales else "en"
    out = []
    for event_id, hidden in page_rows:
        if hidden:
            out.append(MineItem(follow_id=handle[event_id], hidden=True))
            continue
        event = events[event_id]
        calendar = calendars[event.calendar_id]
        title, lang = pick_title(texts.get(event_id, {}), locale, default)
        out.append(
            MineItem(
                follow_id=handle[event_id],
                event_id=event_id,
                title=title,
                lang=lang,
                calendar=MineCalendar(calendar.id, calendar.name, calendar.color),
                leads=tuple(sorted(leads[event_id])),
                next_start=next(iter(upcoming[event_id]), None),
            )
        )
    return out
