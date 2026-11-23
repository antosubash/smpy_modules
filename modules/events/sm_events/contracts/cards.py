"""Event cards for another module (a newsletter's event picker, a block).

A card is what the anonymous public surface shows of one event, and nothing else. Only rows of
:func:`~sm_events.core.access.public.public_events` are ever found or carded (published, not
trashed, on an untrashed ``public`` calendar), so a draft, an in-review or scheduled event, an
internal or private calendar's event, a trashed one and another tenant's are all the same
answer: ``None`` from :func:`get_event_card`, never a search hit. Nothing tells them apart.

The caller names the tenant and it is pinned *here*, twice: bound with
:func:`sm_events.core.tenancy.tenant_scope` (re-entering the bound tenant is a no-op; naming a
different one raises ``TenantIsolationError``) and added as a ``WHERE`` on ``Event.tenant_id``,
because on a host with nothing bound the framework's filter does nothing and an unpinned read
lists every tenant. An invalid ``tenant_id`` raises ``ValueError`` before any SQL runs. A strict
session with nothing bound (``MissingTenantError``) answers "nothing found".

``path`` and ``ics_path`` are site-relative and locale-prefixed except for the default language,
and ``image_url`` is a path on the site or ``""`` (never an off-site address); the caller makes
the paths absolute from its own public origin. Dates stay instants plus the event's timezone: the
caller formats them in its own language.

``pattern`` is a SQL ``LIKE`` pattern with ``\\`` as the escape character; the caller owns
escaping (``simple_module_db.like_contains_pattern``). It matches any of the event's titles.

:func:`mounted` says whether events runs on an app at all, so a caller never reads
``app.state.sm_events`` itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from simple_module_db import MissingTenantError
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from sm_events.content.cards import EventCard, cards_for
from sm_events.contracts import mounted
from sm_events.core import clock, constants
from sm_events.core.access.public import public_events
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Event, EventText

__all__ = ["MAX_EVENT_SEARCH_LIMIT", "EventCard", "get_event_card", "mounted", "search_events"]

MAX_EVENT_SEARCH_LIMIT = constants.MAX_EVENT_SEARCH_LIMIT
"""The most cards one search returns."""

_ESCAPE = "\\"


def _checked_limit(limit: object) -> int:
    # `bool` is an `int`; `True` as a limit is a caller bug, not "one row".
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ValueError(f"limit must be an int, got {type(limit).__name__}")
    if not 1 <= limit <= MAX_EVENT_SEARCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_EVENT_SEARCH_LIMIT}, got {limit}")
    return limit


def _upcoming(now: datetime) -> Any:
    """Not over yet: a one-off that has not ended, or a series that may still repeat."""
    return or_(
        and_(col(Event.rrule).is_(None), col(Event.ends_at) > now),
        and_(
            col(Event.rrule).is_not(None),
            or_(col(Event.recurrence_until).is_(None), col(Event.recurrence_until) > now),
        ),
    )


async def get_event_card(
    session: AsyncSession, *, tenant_id: str, event_id: uuid.UUID, locale: str | None = None
) -> EventCard | None:
    """The card for one event, or ``None`` for an unknown, unpublished, trashed, hidden or
    other-tenant id, and for a series with no occurrence left in the next 366 days.

    A one-off is carded whatever its date; a series at its next occurrence (one in progress
    counts). The text is ``locale``'s, else the default language's, else the first."""
    if not isinstance(event_id, uuid.UUID):
        raise ValueError(f"event_id must be a UUID, got {type(event_id).__name__}")
    with tenant_scope(tenant_id):
        stmt = public_events().where(col(Event.tenant_id) == tenant_id, col(Event.id) == event_id)
        try:
            rows = list((await session.execute(stmt)).scalars().all())
            cards = await cards_for(
                session, rows, tenant_id=tenant_id, locale=locale, now=clock.now()
            )
        except MissingTenantError:
            return None
    return cards[0] if cards else None


async def search_events(
    session: AsyncSession,
    *,
    tenant_id: str,
    pattern: str,
    locale: str | None = None,
    limit: int = 20,
    upcoming_only: bool = True,
) -> list[EventCard]:
    """Events whose title (in any language) matches ``pattern``, as cards.

    Upcoming ones first by start; with ``upcoming_only=False`` the past one-offs follow, newest
    first. At most ``limit`` (1..:data:`MAX_EVENT_SEARCH_LIMIT`) cards, chosen from at most
    ``CARD_SEARCH_SCAN`` matching events of each kind, so a long list is narrowed by typing more.
    """
    limit = _checked_limit(limit)
    if not isinstance(pattern, str):
        raise ValueError(f"pattern must be a str, got {type(pattern).__name__}")
    with tenant_scope(tenant_id):
        now = clock.now()
        titled = select(col(EventText.event_id)).where(
            col(EventText.tenant_id) == tenant_id,
            col(EventText.title).ilike(pattern, escape=_ESCAPE),
        )
        matching = public_events().where(
            col(Event.tenant_id) == tenant_id, col(Event.id).in_(titled)
        )
        coming = (
            matching.where(_upcoming(now))
            .order_by(col(Event.starts_at), col(Event.id))
            .limit(constants.CARD_SEARCH_SCAN)
        )
        past = (
            matching.where(col(Event.rrule).is_(None), col(Event.ends_at) <= now)
            .order_by(col(Event.starts_at).desc(), col(Event.id).desc())
            .limit(constants.CARD_SEARCH_SCAN)
        )
        try:
            rows = list((await session.execute(coming)).scalars().all())
            if not upcoming_only:
                rows += list((await session.execute(past)).scalars().all())
            cards = await cards_for(session, rows, tenant_id=tenant_id, locale=locale, now=now)
        except MissingTenantError:
            return []
    ahead = sorted((c for c in cards if c.ends_at > now), key=lambda c: (c.starts_at, str(c.id)))
    over = sorted(
        (c for c in cards if c.ends_at <= now), key=lambda c: (c.starts_at, str(c.id)), reverse=True
    )
    return [*ahead, *over][:limit]
