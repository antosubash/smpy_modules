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
from sqlalchemy.orm.attributes import set_committed_value

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
    )
    won = (await db.execute(stmt)).scalar_one_or_none()
    if won is not None:
        return won
    current = (await db.execute(select(table.c.revision).where(*where))).scalar_one_or_none()
    if current is None:
        raise NotFound
    raise Stale(current)


async def claim(
    db: Any, event: Event, expected: int, *, actor: str | None, trashed: bool = False
) -> int:
    """:func:`claim_revision`, then the loaded ``event`` told what the database
    now says (without marking it dirty, so the ORM never writes it back)."""
    number = await claim_revision(db, event.id, expected, actor=actor, trashed=trashed)
    set_committed_value(event, "revision", number)
    set_committed_value(event, "updated_by", actor)
    return number
