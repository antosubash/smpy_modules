"""\"My reminders\": the caller's own follows on events they can see now.

A follow on an event the caller can no longer see (unpublished, trashed, a share removed) is
counted in ``hidden`` and never named: its title, calendar and time are not theirs to read any
more. Only the caller's own rows are read; nothing here shows who else follows anything.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import func, select

from sm_events.core import constants
from sm_events.core.access.events import visible_events
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Calendar, Event, EventFollow, EventText
from sm_events.reminders import candidates
from sm_events.reminders.limits import MINE_PAGE_MAX
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
    event_id: uuid.UUID
    title: str
    lang: str
    calendar: MineCalendar
    leads: tuple[int, ...]
    next_start: datetime | None


@dataclass(frozen=True)
class MinePage:
    items: list[MineItem]
    total: int
    """Followed events the caller can see now."""
    hidden: int
    """Followed events they cannot (counted, never named)."""
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
    user_id = who.user_id
    if user_id is None or not who.has(constants.PERM_VIEW):
        return MinePage([], 0, 0, page, page_size)
    mine = (_F.c.tenant_id == bound_tenant(), _F.c.user_id == user_id)
    visible = visible_events(who, include_unpublished=False).with_only_columns(Event.id)
    seen = (*mine, _F.c.event_id.in_(visible))

    followed = (
        await db.execute(select(func.count(func.distinct(_F.c.event_id))).where(*mine))
    ).scalar_one()
    total = (
        await db.execute(select(func.count(func.distinct(_F.c.event_id))).where(*seen))
    ).scalar_one()
    since = func.min(_F.c.created_at)
    ids = [
        row[0]
        for row in await db.execute(
            select(_F.c.event_id)
            .where(*seen)
            .group_by(_F.c.event_id)
            .order_by(since.desc(), _F.c.event_id)
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ]
    items = await _items(db, user_id, ids, locale=locale, settings=settings, now=now)
    return MinePage(items, int(total), int(followed - total), page, page_size)


async def _items(
    db: Any,
    user_id: str,
    ids: list[uuid.UUID],
    *,
    locale: str,
    settings: EventsSettings,
    now: datetime,
) -> list[MineItem]:
    if not ids:
        return []
    events = {
        e.id: e
        for e in (await db.execute(select(Event).where(Event.id.in_(ids)))).scalars()  # type: ignore[attr-defined]
    }
    calendars = {
        c.id: c
        for c in (
            await db.execute(
                select(Calendar).where(Calendar.id.in_({e.calendar_id for e in events.values()}))  # type: ignore[attr-defined]
            )
        ).scalars()
    }
    texts: dict[uuid.UUID, dict[str, EventText]] = {}
    for text in (
        await db.execute(select(EventText).where(EventText.event_id.in_(ids)))  # type: ignore[attr-defined]
    ).scalars():
        texts.setdefault(text.event_id, {})[text.locale] = text
    leads: dict[uuid.UUID, list[int]] = {}
    for event_id, lead in await db.execute(
        select(_F.c.event_id, _F.c.lead_minutes).where(
            _F.c.tenant_id == bound_tenant(), _F.c.user_id == user_id, _F.c.event_id.in_(ids)
        )
    ):
        leads.setdefault(event_id, []).append(lead)
    upcoming = await candidates.next_starts(db, list(events.values()), now=now)
    default = settings.content_locales[0] if settings.content_locales else "en"
    out = []
    for event_id in ids:
        event = events[event_id]
        calendar = calendars[event.calendar_id]
        title, lang = pick_title(texts.get(event_id, {}), locale, default)
        out.append(
            MineItem(
                event_id=event_id,
                title=title,
                lang=lang,
                calendar=MineCalendar(calendar.id, calendar.name, calendar.color),
                leads=tuple(sorted(leads[event_id])),
                next_start=next(iter(upcoming[event_id]), None),
            )
        )
    return out
