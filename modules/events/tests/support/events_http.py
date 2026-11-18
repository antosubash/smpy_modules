"""Seeding and request helpers for the events HTTP tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sm_events.models import Event

from tests.support.access import seed_calendars
from tests.support.app import as_user
from tests.support.writes import OWNER_P, make

V, E, P, M = "events.view", "events.edit", "events.publish", "events.manage"
BASE = "/api/events"
EV = f"{BASE}/events"

OWNER = as_user("o", V, E)  # the cast's owner, no publish
OWNER_PUB = as_user("o", V, E, P)
STRANGER = as_user("z", V, E)  # signed in, no share, not the owner
SHARE_VIEW = as_user("sv", V)
SHARE_EDIT = as_user("se", V)
MANAGER = as_user("m", V, M)
MANAGER_PUB = as_user("m", V, M, P)
VIEWER = as_user("v", V)
ANON = {}


async def run(client, fn):
    """Run ``fn(session)`` in its own session and commit; its (plain) result."""
    async with client.db_state.session_factory() as session:
        out = await fn(session)
        await session.commit()
        return out


async def cast(client) -> dict[str, str]:
    """The three access-cast calendars (``P``, ``I``, ``U``) by id."""

    async def seed(db):
        return {k: str(c.id) for k, c in (await seed_calendars(db)).items()}

    return await run(client, seed)


async def seed_event(
    client, calendar_id: str, *, status: str = "draft", rrule: str | None = None, **body: Any
) -> dict[str, Any]:
    """An event made through the service (so it has its revision row), in
    ``status``. ``{"id", "revision"}``."""
    import uuid

    from sm_events.models import Calendar
    from sqlalchemy import select

    async def go(db):
        cal = (
            await db.execute(select(Calendar).where(Calendar.id == uuid.UUID(calendar_id)))
        ).scalar_one()
        event = await make(db, OWNER_P, cal, **({"rrule": rrule} if rrule else {}), **body)
        if status != "draft":
            event.status = status
            if status == "published":
                event.published_at = datetime(2026, 6, 1, tzinfo=UTC)
            await db.flush()
        return {"id": str(event.id), "revision": event.revision}

    return await run(client, go)


def create_json(calendar_id: str, **kw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "calendar_id": calendar_id,
        "times": {
            "timezone": "Europe/Vienna",
            "start": "2026-07-01T10:00",
            "end": "2026-07-01T11:00",
        },
        "texts": {"en": {"title": "Concert"}},
    }
    out.update(kw)
    return out


async def create(client, calendar_id: str, headers=OWNER, **kw: Any) -> dict[str, Any]:
    got = await client.post(EV, json=create_json(calendar_id, **kw), headers=headers)
    assert got.status_code == 201, got.text
    return got.json()


async def stored(client, event_id: str) -> Event:
    import uuid

    from sqlalchemy import select

    async def go(db):
        row = (
            await db.execute(
                select(Event)
                .where(Event.id == uuid.UUID(event_id))
                .execution_options(include_deleted=True)
            )
        ).scalar_one()
        return {"revision": row.revision, "status": row.status, "is_deleted": row.is_deleted}

    return await run(client, go)  # type: ignore[return-value]
