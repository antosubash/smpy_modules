"""Redirects from a slug a calendar used to have.

A row is ``(old_slug) -> calendar id`` per tenant, so a chain of renames (``a`` to ``b`` to
``c``) needs no following: ``a`` and ``b`` both point at the calendar, whose slug is now
``c``. A calendar that claims a slug (created with it, renamed to it, renamed back to it)
removes any redirect on it, so whoever holds a slug wins over an old link.

Every statement carries its own ``tenant_id`` predicate. The public side asks
:func:`resolve`, which answers only for a calendar the anonymous visitor may see, so a
301 never confirms that a private or trashed calendar ever had that address.

The insert is the one write here that can lose a race on the unique key. It runs in a
savepoint opened before the insert and is recognised the way the slug writes are (sqlstate
23505 and the constraint's name on Postgres, the exact message on SQLite), so a lost race
repoints the row and never leaves the request's transaction aborted.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlmodel import col

from sm_events.calendar.slugs import is_slug_conflict
from sm_events.content.public_read import valid_slug
from sm_events.core.access.public import public_calendars
from sm_events.core.clock import utcnow
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Calendar, CalendarRedirect
from sm_events.models.calendar_redirect import CALENDAR_REDIRECT_CONSTRAINT

__all__ = ["record_rename", "release_slug", "resolve"]


async def release_slug(db: Any, slug: str) -> None:
    """Delete the redirect on ``slug``: its new holder wins."""
    table = CalendarRedirect.__table__  # type: ignore[attr-defined]
    await db.execute(
        delete(table).where(table.c.tenant_id == bound_tenant(), table.c.old_slug == slug)
    )


async def _existing(db: Any, slug: str) -> CalendarRedirect | None:
    stmt = select(CalendarRedirect).where(
        CalendarRedirect.tenant_id == bound_tenant(),  # type: ignore[arg-type]
        CalendarRedirect.old_slug == slug,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _repoint(db: Any, row: CalendarRedirect, calendar_id: uuid.UUID) -> None:
    row.calendar_id = calendar_id
    row.created_at = utcnow()
    await db.flush()


async def record_rename(db: Any, *, calendar_id: uuid.UUID, old_slug: str) -> None:
    """Remember ``old_slug`` as pointing at the calendar. A redirect already on it is
    repointed; losing a race on the unique key does the same, in a savepoint."""
    if (row := await _existing(db, old_slug)) is not None:
        await _repoint(db, row, calendar_id)
        return
    try:
        async with db.begin_nested():
            db.add(CalendarRedirect(calendar_id=calendar_id, old_slug=old_slug))
            await db.flush()
    except IntegrityError as exc:
        if not is_slug_conflict(exc, CALENDAR_REDIRECT_CONSTRAINT):
            raise
        winner = await _existing(db, old_slug)
        if winner is None:  # pragma: no cover - the other transaction rolled back
            raise
        await _repoint(db, winner, calendar_id)


async def resolve(db: Any, slug: str) -> str | None:
    """The current slug of the calendar an old ``slug`` pointed at, only if that
    calendar is public (trashed and non-public ones are not: Ruling 3). A redirect
    onto its own slug is ``None``."""
    if not valid_slug(slug):
        return None
    stmt = (
        public_calendars()
        .join(CalendarRedirect, col(CalendarRedirect.calendar_id) == col(Calendar.id))
        .where(
            CalendarRedirect.tenant_id == bound_tenant(),  # type: ignore[arg-type]
            CalendarRedirect.old_slug == slug,
        )
        .with_only_columns(Calendar.slug)
    )
    current = (await db.execute(stmt)).scalars().first()
    return None if current in (None, slug) else current
