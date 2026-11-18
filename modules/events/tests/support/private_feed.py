"""A private feed's world: calendars and events in a tenant, and links to them."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from httpx import AsyncClient
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.tokens import service
from sm_events.models import Calendar, Event, EventText

from tests.support.access import principal, seed_calendars
from tests.support.app import public_http
from tests.support.calendars import seed_event
from tests.support.public import tenant_header
from tests.support.tokens import NOW, fake_request, install_directory, install_members

V = "events.view"
IGNORED = frozenset({"date", "x-correlation-id"})
EVERYONE = {"o", "sv", "se", "v", "m", "e", "a", "x"}
MEMBERS = {"default": set(EVERYONE), "a": set(EVERYONE), "b": {"sv"}}


def fingerprint(response):
    """Status, body and every header but the clock and the request id."""
    headers = {k: v for k, v in response.headers.items() if k not in IGNORED}
    return response.status_code, response.content, headers


@asynccontextmanager
async def private_http(
    *,
    multi: bool = False,
    settings: dict | None = None,
    members: dict[str, set[str]] | None = None,
) -> AsyncIterator[AsyncClient]:
    """The public surface plus a user directory (and, on a multi-tenant host, memberships)."""

    def before_wire(app: Any) -> None:
        install_directory(app)
        if multi:
            install_members(app, members if members is not None else {})

    async with public_http(multi=multi, settings=settings, before_wire=before_wire) as http:
        yield http


@dataclass
class World:
    http: AsyncClient
    tenant: str
    cals: dict[str, Calendar]
    pub: Event
    draft: Event
    secret: str
    token_id: Any

    @property
    def path(self) -> str:
        return feed_path(self.secret)


def feed_path(secret: str) -> str:
    return f"/events/feed/{secret}.ics"


def invented(fill: str = "Z") -> str:
    """A well-formed token nobody holds."""
    return "evf_" + fill * 43


async def mint(
    http: AsyncClient,
    calendar: Calendar,
    *,
    user: str = "sv",
    tenant: str = "default",
    locale: str = "en",
    perms: tuple[str, ...] = (V,),
) -> Any:
    with tenant_scope(tenant):
        async with http.db_state.session_factory() as db:
            got = await service.create_token(
                db,
                fake_request(http.app),
                principal(user, *perms),
                calendar.id,
                label="Phone",
                locale=locale,
                now=NOW,
            )
            await db.commit()
            return got


async def seed_world(http: AsyncClient, *, tenant: str = "default", tag: str = "") -> World:
    """Calendars ``P`` (private, shared with ``sv``), ``I`` and ``U``; a published and a
    draft event in ``P``; a link for ``sv`` on ``P``."""
    with tenant_scope(tenant):
        async with http.db_state.session_factory() as db:
            cals = await seed_calendars(db)
            pub = await seed_event(
                db, cals["P"], title=f"Published{tag}", status="published", slug=f"published{tag}"
            )
            draft = await seed_event(
                db, cals["P"], title=f"Secret draft{tag}", status="draft", slug=f"draft{tag}"
            )
            await db.commit()
    created = await mint(http, cals["P"], tenant=tenant)
    return World(http, tenant, cals, pub, draft, created.secret, created.token.id)


async def add_text(http: AsyncClient, event: Event, locale: str, title: str, tenant="default"):
    with tenant_scope(tenant):
        async with http.db_state.session_factory() as db:
            db.add(
                EventText(
                    event_id=event.id, locale=locale, slug=f"{title.lower()}-{locale}", title=title
                )
            )
            await db.commit()


__all__ = [
    "EVERYONE",
    "MEMBERS",
    "World",
    "add_text",
    "feed_path",
    "fingerprint",
    "invented",
    "mint",
    "private_http",
    "seed_world",
    "tenant_header",
]
