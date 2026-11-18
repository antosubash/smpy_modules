"""The import's lease: the claim, and the one guard every later state write passes.

A copy of newsletter's ``imports/fence.py`` over :class:`~sm_events.models.EventImport`, with two
claimable states: ``uploaded`` (to be parsed) becomes ``parsing`` and ``queued`` (to be applied)
becomes ``running``, as one ``UPDATE`` for a fresh owner. A ``parsing`` or ``running`` import whose
lease ran out is claimed again in place, which is how a crashed slice resumes.

After the claim every write to the row goes through :func:`fenced`: an ``UPDATE`` that matches
only while ``lease_owner`` is this owner and the status is ``parsing`` or ``running``. A zero-row
match raises :class:`LeaseLost`, and the caller rolls back, so writes to other tables in the same
transaction (items, events) are committed only if the guard matched. Nothing here commits.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from simple_module_db import mark_written
from sqlalchemy import case, or_, select, update

from sm_events.core import constants
from sm_events.models import EventImport

__all__ = ["CLAIMABLE", "WORKING", "Claim", "LeaseLost", "claim", "fenced"]

CLAIMABLE = ("uploaded", "queued", "parsing", "running")
WORKING = ("parsing", "running")


class LeaseLost(Exception):  # noqa: N818 - the state it reports
    """The guard matched no row: another worker owns the import, or it left its working state."""


@dataclass(frozen=True)
class Claim:
    kind: Literal["claimed", "busy", "gone"]
    status: str | None = None
    """The state the import is in after a successful claim (``parsing`` or ``running``)."""
    attempts: int = 0
    """How many times an unfinished parse has been claimed, this claim included."""


async def claim(db: Any, *, tenant_id: str, import_id: int, owner: str, now: datetime) -> Claim:
    """Take an import nobody holds (or whose lease ran out) for ``owner``."""
    table = EventImport.__table__
    stmt = (
        update(table)
        .where(
            table.c.id == import_id,
            table.c.tenant_id == tenant_id,
            table.c.status.in_(CLAIMABLE),
            or_(table.c.lease_owner.is_(None), table.c.lease_until < now),
        )
        .values(
            status=case(
                (table.c.status == "uploaded", "parsing"),
                (table.c.status == "queued", "running"),
                else_=table.c.status,
            ),
            attempts=case(
                (table.c.status.in_(("uploaded", "parsing")), table.c.attempts + 1),
                else_=table.c.attempts,
            ),
            lease_owner=owner,
            lease_until=now + constants.IMPORT_LEASE,
        )
        .execution_options(synchronize_session=False)
    )
    if (await db.execute(stmt)).rowcount == 1:
        mark_written(db)
        status, attempts = (
            await db.execute(
                select(table.c.status, table.c.attempts).where(
                    table.c.id == import_id, table.c.tenant_id == tenant_id
                )
            )
        ).one()
        return Claim("claimed", status, attempts)
    status = (
        await db.execute(
            select(table.c.status).where(table.c.id == import_id, table.c.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    return Claim("busy" if status in CLAIMABLE else "gone")


async def fenced(
    db: Any, *, tenant_id: str, import_id: int, owner: str, values: dict[str, Any]
) -> None:
    """``UPDATE`` the import while ``owner`` holds it; :class:`LeaseLost` otherwise."""
    table = EventImport.__table__
    stmt = (
        update(table)
        .where(
            table.c.id == import_id,
            table.c.tenant_id == tenant_id,
            table.c.lease_owner == owner,
            table.c.status.in_(WORKING),
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if (await db.execute(stmt)).rowcount != 1:
        raise LeaseLost
    mark_written(db)
