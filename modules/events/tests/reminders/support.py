"""The cast the follow and reminder tests share: calendars, principals, published events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sharing.core.policy import canonical_id
from sharing.models import ResourceShare
from sm_events.core.settings import EventsSettings
from sm_events.models import Calendar, Event, EventFollow
from sqlalchemy import select

from tests.support.access import principal, seed_calendars
from tests.support.calendars import seed_event

V, E, P, M = "events.view", "events.edit", "events.publish", "events.manage"
NOW = datetime(2026, 7, 1, 8, tzinfo=UTC)
SETTINGS = EventsSettings()

U = principal("u", V)
OTHER = principal("w", V)
STRANGER = principal("z", V)
MANAGER = principal("m", V, M)
ANON = principal(None)
NO_VIEW = principal("o")  # the cast's owner, without ``events.view``
VIEW_SHARE = principal("sv", V)
EDIT_SHARE = principal("se", V)


async def world(db: Any) -> dict[str, Calendar]:
    return await seed_calendars(db)


async def published(db: Any, calendar: Calendar, title: str = "Talk", **fields: Any) -> Event:
    fields.setdefault("status", "published")
    fields.setdefault("starts_at", NOW + timedelta(days=3))
    return await seed_event(db, calendar, title=title, **fields)


def follow_row(event: Event, user: str = "u", lead: int = 60, locale: str = "en") -> EventFollow:
    return EventFollow(event_id=event.id, user_id=user, lead_minutes=lead, locale=locale)


async def drop_share(db: Any, calendar: Calendar, user: str) -> None:
    """Remove ``user``'s share on ``calendar`` (the cast gives ``sv`` and ``se`` one on each)."""
    rows = await db.execute(
        select(ResourceShare).where(
            ResourceShare.resource_id == canonical_id(calendar.id),
            ResourceShare.subject_id == user,
        )
    )
    for row in rows.scalars():
        await db.delete(row)
    await db.flush()
