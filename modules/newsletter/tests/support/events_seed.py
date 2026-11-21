"""Events for the event-card tests, written straight to events' tables (a test-only import:
module code reads events only through ``sm_events.contracts.cards``)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sm_events.core.tenancy import tenant_scope
from sm_events.models import Calendar, Event, EventText, Visibility
from sqlalchemy import update

STARTS = datetime(2026, 7, 1, 8, tzinfo=UTC)


async def seed_event(
    db_state: Any,
    tenant: str,
    *,
    slug: str = "open-day",
    title: str = "Open day",
    summary: str | None = None,
    visibility: Visibility = Visibility.PUBLIC,
    status: str = "published",
    starts_at: datetime = STARTS,
    texts: dict[str, tuple[str, str]] | None = None,
    **fields: Any,
) -> uuid.UUID:
    """An event (on a fresh calendar) in ``tenant``; its id. ``fields`` are ``Event`` columns;
    ``texts`` adds ``{locale: (slug, title)}`` beside the English one."""
    fields.setdefault("ends_at", starts_at + timedelta(hours=1))
    fields.setdefault("timezone", "Europe/Vienna")
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            calendar = Calendar(
                slug=f"cal-{uuid.uuid4().hex[:8]}",
                name="Calendar",
                owner_id="o",
                visibility=visibility,
            )
            db.add(calendar)
            await db.flush()
            event = Event(
                calendar_id=calendar.id,
                starts_at=starts_at,
                status=status,
                uid=f"{uuid.uuid4()}@simple-module-events",
                **fields,
            )
            db.add(event)
            await db.flush()
            db.add(
                EventText(event_id=event.id, locale="en", slug=slug, title=title, summary=summary)
            )
            for locale, (text_slug, text_title) in (texts or {}).items():
                db.add(
                    EventText(event_id=event.id, locale=locale, slug=text_slug, title=text_title)
                )
            await db.commit()
            return event.id


async def change_event(db_state: Any, tenant: str, event_id: uuid.UUID, **values: Any) -> None:
    """Write ``values`` onto the event (``status``, ``cancelled``, ``is_deleted``...)."""
    with tenant_scope(tenant):
        async with db_state.session_factory() as db:
            stmt = (
                update(Event)
                .where(Event.id == event_id, Event.tenant_id == tenant)  # type: ignore[arg-type]
                .values(**values)
                .execution_options(include_deleted=True)
            )
            await db.execute(stmt)
            await db.commit()
