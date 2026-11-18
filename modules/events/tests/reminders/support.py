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


# --- the HTTP cast -------------------------------------------------------------------------

ORIGIN = "https://events.example.org"


class _Delivers:
    delivers_email = True

    async def send(self, message) -> None:  # pragma: no cover - the API tests never send
        raise AssertionError("an API test sent mail")


def make_ready(app: Any, monkeypatch: Any) -> None:
    """Everything reminders need to be available: a base URL, a delivering sender and a worker
    runtime. Each test breaks what it wants to break."""
    from simple_module_core.mail import install_mail_sender
    from sm_events.reminders import worker_app

    app.state.sm.settings.public_base_url = ORIGIN
    install_mail_sender(_Delivers())
    monkeypatch.setattr(worker_app, "worker_runtime_supported", lambda: True)


async def seed_http(client: Any, tenant: str = "default") -> dict[str, Any]:
    """The cast's calendars with a published and a draft event in each, committed.
    ``{"P": cal, "pub": {"P": event, ...}, "draft": {...}}`` (ids are read, so no refresh)."""
    from sm_events.core.tenancy import tenant_scope

    with tenant_scope(tenant):
        async with client.db_state.session_factory() as db:
            cals = await seed_calendars(db)
            pub = {k: await published(db, c, title=f"Pub {k}") for k, c in cals.items()}
            drafts = {
                k: await published(db, c, title=f"Draft {k}", status="draft")
                for k, c in cals.items()
            }
            ids = {
                "cal": {k: str(c.id) for k, c in cals.items()},
                "pub": {k: str(e.id) for k, e in pub.items()},
                "draft": {k: str(e.id) for k, e in drafts.items()},
            }
            await db.commit()
    return ids
