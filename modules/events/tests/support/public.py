"""Seeding and request helpers for the public surface's tests."""

from __future__ import annotations

from typing import Any

from sm_events.core.tenancy import tenant_scope
from sm_events.models import EventText

from tests.support.calendars import PublicFixture, seed_public_fixture

INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "test"}
"""What an in-app visit sends; the answer is the page's JSON."""


async def add_german(db: Any, fx: PublicFixture) -> None:
    """A ``de`` text on every event that lacks one, so a locale prefix cannot be what hides
    a hidden event: its German address exists and must still be the 404."""
    events = [*fx.public_events, *fx.hidden.values()]
    for event in events:
        if f"{event.id}:de" in fx.slugs:
            continue
        slug = f"{fx.slug(event)}-de"
        db.add(EventText(event_id=event.id, locale="de", slug=slug, title=f"{slug.title()}"))
        fx.slugs[f"{event.id}:de"] = slug
    await db.flush()


async def seed_public(
    client: Any, *, tag: str = "", tenant: str = "default", german: bool = True
) -> PublicFixture:
    """The fixture, committed through ``client``'s database, in ``tenant``. The returned
    object's ORM rows are detached; read ids and ``fx.slugs``, not lazy attributes."""
    with tenant_scope(tenant):
        async with client.db_state.session_factory() as session:
            fx = await seed_public_fixture(session, tag)
            if german:
                await add_german(session, fx)
            await session.commit()
    return fx


def tenant_header(tenant: str) -> dict[str, str]:
    """What makes a request resolve ``tenant`` on the multi-tenant harness app."""
    return {"X-Test-Tenant": tenant}
