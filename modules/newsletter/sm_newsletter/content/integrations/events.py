"""Event cards through ``sm_events.contracts.cards`` (the ``events`` extra).

The tenant is the caller's bound one, passed explicitly; the contract pins it and answers only
published events of public calendars, so a draft can never reach a snapshot. This package is
the only one in newsletter that names ``sm_events``.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.content.integrations._guard import Guard
from sm_newsletter.content.integrations.hits import SEARCH_LIMIT, EventHit, like_pattern

_GUARD = Guard("sm_events.contracts.cards")


def available(app: Any) -> bool:
    """The contract imports and events is mounted on ``app``."""
    return _GUARD.available(app)


_require = _GUARD.require


def _hit(card: Any) -> EventHit:
    return EventHit(
        kind="event",
        source_id=str(card.id),
        title=card.title,
        excerpt=card.summary,
        image_url=card.image_url,
        url=card.path,
        ics_url=card.ics_path,
        locale=card.locale,
        starts_at=card.starts_at,
        ends_at=card.ends_at,
        all_day=card.all_day,
        start_date=card.start_date,
        end_date=card.end_date,
        timezone=card.timezone,
        attendance_mode=card.attendance_mode,
        place=", ".join(part for part in (card.venue_name, card.address) if part),
        cancelled=card.cancelled,
    )


async def search(
    app: Any, session: AsyncSession, *, tenant_id: str, q: str, locale: str | None
) -> list[EventHit]:
    """Upcoming published public events of ``tenant_id`` whose title contains ``q``."""
    contract = _require(app)
    cards = await contract.search_events(
        session,
        tenant_id=tenant_id,
        pattern=like_pattern(q),
        locale=locale,
        limit=SEARCH_LIMIT,
        upcoming_only=True,
    )
    return [_hit(c) for c in cards]


async def card(
    app: Any, session: AsyncSession, *, tenant_id: str, source_id: str
) -> EventHit | None:
    """The card of event ``source_id`` (a UUID) of ``tenant_id``, or ``None``: unknown, not
    public, or a string that is no UUID (the contract is not asked)."""
    contract = _require(app)
    try:
        event_id = uuid.UUID(source_id)
    except (ValueError, AttributeError, TypeError):
        return None
    found = await contract.get_event_card(session, tenant_id=tenant_id, event_id=event_id)
    return None if found is None else _hit(found)
