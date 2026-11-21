"""Per-language redirects from a slug an event used to have.

A redirect is ``(locale, old_slug) -> event``. Renaming the ``de`` slug records a
``de`` redirect only; an event that claims a slug removes any redirect on it, so
whoever holds a slug now wins over an old link, and renaming back removes the
redirect. Every statement carries its own ``tenant_id`` predicate.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from sm_events.core.clock import utcnow
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Redirect

__all__ = ["record_rename", "release_slug"]


async def release_slug(db: Any, *, locale: str, slug: str) -> None:
    """Delete the redirect on ``(locale, slug)``: its new holder wins."""
    table = Redirect.__table__  # type: ignore[attr-defined]
    await db.execute(
        delete(table).where(
            table.c.tenant_id == bound_tenant(),
            table.c.locale == locale,
            table.c.old_slug == slug,
        )
    )


async def _repoint(db: Any, locale: str, old_slug: str, event_id: uuid.UUID) -> None:
    row = (
        await db.execute(
            select(Redirect).where(Redirect.locale == locale, Redirect.old_slug == old_slug)
        )
    ).scalar_one()
    row.event_id = event_id
    row.created_at = utcnow()
    await db.flush()


async def record_rename(db: Any, *, event_id: uuid.UUID, locale: str, old_slug: str) -> None:
    """Remember ``old_slug`` in ``locale`` as pointing at the event. An existing
    redirect on it is repointed; losing a race on the unique key does the same
    in a savepoint, so the caller's transaction is never left aborted."""
    existing = (
        await db.execute(
            select(Redirect).where(Redirect.locale == locale, Redirect.old_slug == old_slug)
        )
    ).scalar_one_or_none()
    if existing is not None:
        await _repoint(db, locale, old_slug, event_id)
        return
    try:
        async with db.begin_nested():
            db.add(Redirect(event_id=event_id, locale=locale, old_slug=old_slug))
            await db.flush()
    except IntegrityError:
        await _repoint(db, locale, old_slug, event_id)
