"""Calendar HTTP setup shared by the API tests."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sm_events.calendar import rrule
from sm_events.calendar.times import to_span
from sm_events.models import Calendar, Event, EventText

from tests.support.app import as_user

V, E, P, M = "events.view", "events.edit", "events.publish", "events.manage"
BASE = "/api/events/calendars"
OWNER = as_user("o", V, E)
OWNER_P = as_user("o", V, E, P)
VIEWER = as_user("v", V)
EDITOR = as_user("e", V, E)
MANAGER = as_user("m", V, M)
SV = as_user("sv", V)
SE = as_user("se", V)


async def make(client, headers=OWNER, **body):
    body.setdefault("name", "Team")
    got = await client.post(BASE, json=body, headers=headers)
    assert got.status_code == 201, got.text
    return got.json()


async def bare_event(db: Any, calendar: Calendar, **fields: Any) -> Event:
    """An ``Event`` row with no text (what ``create_event`` inserts before its
    texts). ``fields`` are ``Event`` columns; the defaults are a one-hour draft on
    2026-07-01 in UTC."""
    start = fields.pop("starts_at", datetime(2026, 7, 1, 10, tzinfo=UTC))
    fields.setdefault("ends_at", start + timedelta(hours=1))
    fields.setdefault("timezone", "UTC")
    fields.setdefault("uid", f"{uuid.uuid4()}@simple-module-events")
    event = Event(calendar_id=calendar.id, starts_at=start, **fields)
    db.add(event)
    await db.flush()
    return event


async def seed_event(
    db: Any,
    calendar: Calendar,
    *,
    title: str = "Event",
    locale: str = "en",
    slug: str | None = None,
    **fields: Any,
) -> Event:
    """Insert an event and its text straight into the database (no service, no
    revision). ``fields`` are ``Event`` columns; the defaults are a one-hour
    draft on 2026-07-01 in UTC."""
    event = await bare_event(db, calendar, **fields)
    db.add(
        EventText(
            event_id=event.id,
            locale=locale,
            slug=slug or f"event-{event.id.hex[:12]}",
            title=title,
        )
    )
    await db.flush()
    return event


async def seed_series(
    db: Any,
    calendar: Calendar,
    text: str,
    start: str,
    end: str,
    *,
    tz: str = "Europe/Vienna",
    all_day: bool = False,
    **fields: Any,
) -> Event:
    """A recurring event, its span and ``recurrence_until`` derived the way the
    service will derive them. ``start``/``end`` are local wall-clock input."""
    span = to_span(all_day=all_day, timezone=tz, start=start, end=end, recurring=True)
    rule = rrule.parse(text, all_day=all_day, timezone=tz)
    until = rrule.validate(rule, span, all_day=all_day, timezone=tz)
    return await seed_event(
        db,
        calendar,
        starts_at=span.starts_at,
        ends_at=span.ends_at,
        timezone=tz,
        all_day=all_day,
        rrule=rule.text,
        recurrence_until=until,
        **fields,
    )
