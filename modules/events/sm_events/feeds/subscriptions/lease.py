"""The beat's claim on a subscription: compare-and-set, fenced stores, a lease that expires.

``claim`` is one Core ``UPDATE`` whose ``WHERE`` is the whole "is this due and unleased"
predicate (and an install-wide count of live leases under ``SUBSCRIPTION_MAX_CONCURRENT_FETCHES``),
so two workers cannot both win (a row count of one is the win). The fetch runs with no
session open; the result is stored through :func:`fenced`, which only returns the row while the
caller still holds an unexpired lease (a worker that was slow, crashed and was replaced cannot
store). A lease the holder never releases simply expires: the row is due again. Core DML calls
``mark_written`` itself (the framework only commits a session it saw write).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from simple_module_db import all_tenants as framework_all_tenants
from simple_module_db import mark_written
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.sql.elements import ColumnElement

from sm_events.core import constants
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Subscription

__all__ = ["claim", "due", "fenced", "release"]

_LIVE = ("pending", "ok", "error")


def due(now: datetime) -> ColumnElement[bool]:
    """Live (not paused or disabled), not deleted, due, and not under an unexpired lease."""
    table = Subscription.__table__
    return and_(
        table.c.status.in_(_LIVE),
        table.c.is_deleted.is_(False),
        table.c.next_fetch_at.is_not(None),
        table.c.next_fetch_at <= now,
        or_(table.c.lease_until.is_(None), table.c.lease_until < now),
    )


async def claim(db: Any, sub_id: uuid.UUID, *, owner: str, now: datetime) -> bool:
    """Take the lease on ``sub_id`` if it is due. ``True`` for the one caller that won."""
    table = Subscription.__table__
    tenant = bound_tenant()
    active = (
        select(func.count()).select_from(table).where(table.c.lease_until > now).scalar_subquery()
    )
    stmt = (
        update(table)
        .where(
            table.c.tenant_id == tenant,
            table.c.id == sub_id,
            due(now),
            active < constants.SUBSCRIPTION_MAX_CONCURRENT_FETCHES,
        )
        .values(lease_owner=owner, lease_until=now + constants.SUBSCRIPTION_LEASE)
    )
    with framework_all_tenants():  # the count is install-wide; the target names its tenant itself
        result = await db.execute(stmt)
    mark_written(db)
    return result.rowcount == 1


async def fenced(db: Any, sub_id: uuid.UUID, *, owner: str, now: datetime) -> Subscription | None:
    """The row, locked, while ``owner`` still holds its lease; ``None`` once it is lost."""
    stmt = (
        select(Subscription)
        .where(
            Subscription.tenant_id == bound_tenant(),  # type: ignore[arg-type]
            Subscription.id == sub_id,  # type: ignore[arg-type]
            Subscription.lease_owner == owner,  # type: ignore[arg-type]
            Subscription.lease_until > now,  # type: ignore[arg-type]
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalars().first()


async def release(db: Any, sub: Subscription) -> None:
    """Clear the lease on a row :func:`fenced` returned."""
    sub.lease_owner = None
    sub.lease_until = None
    await db.flush()
