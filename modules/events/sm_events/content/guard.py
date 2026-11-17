"""The stale-write guard: a compare-and-set on ``revision``, in SQL.

Every write path starts here. The first statement is one ``UPDATE`` that bumps the
revision only if it still equals what the caller saw, so two writers holding the
same ``expected_revision`` cannot both win, and on Postgres the ``UPDATE`` takes
the row lock first, so the second waits and then loses. A read-then-write would
let both through.

A Core statement, so it carries its own ``tenant_id`` predicate.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update

from sm_events.core.clock import utcnow
from sm_events.core.errors import NotFound, Stale
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Event

__all__ = ["claim", "claim_revision"]


async def claim_revision(
    db: Any, event_id: uuid.UUID, expected: int, *, actor: str | None, trashed: bool = False
) -> int:
    """Move the event from ``expected`` to ``expected + 1``; the new revision.

    ``Stale`` when the event exists at another revision, ``NotFound`` when it is
    gone (or trashed, unless ``trashed``) in the bound tenant."""
    table = Event.__table__  # type: ignore[attr-defined]
    where = (
        table.c.tenant_id == bound_tenant(),
        table.c.id == event_id,
        table.c.is_deleted.is_(trashed),
    )
    stmt = (
        update(table)
        .where(*where, table.c.revision == expected)
        .values(revision=table.c.revision + 1, updated_at=utcnow(), updated_by=actor)
        .returning(table.c.revision)
        .execution_options(include_deleted=trashed)
    )
    won = (await db.execute(stmt)).scalar_one_or_none()
    if won is not None:
        return won
    # The framework's soft-delete criterion reaches Core statements too: only
    # ``include_deleted`` lets this one see the trash.
    peek = select(table.c.revision).where(*where).execution_options(include_deleted=trashed)
    current = (await db.execute(peek)).scalar_one_or_none()
    if current is None:
        raise NotFound
    raise Stale(current)


async def claim(
    db: Any, event: Event, expected: int, *, actor: str | None, trashed: bool = False
) -> int:
    """:func:`claim_revision`, then the loaded ``event`` told what the database
    now says. A plain assignment, not ``set_committed_value``: when the caller's
    savepoint rolls back, the session expires an object it changed, so the event
    never keeps a revision the database does not have. The ORM's own ``UPDATE``
    writes the same value again, which is harmless: the row is already ours."""
    number = await claim_revision(db, event.id, expected, actor=actor, trashed=trashed)
    event.revision = number
    event.updated_by = actor
    return number
