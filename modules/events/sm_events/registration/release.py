"""Release: take seats back, exactly and idempotently (see :mod:`sm_events.registration.seats`).

The counter rows are locked first, in ascending id, then the seats are deleted and every affected
counter is recomputed from the seat rows that remain.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from simple_module_db import mark_written
from sqlalchemy import delete, select

from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.tenancy import tenant_scope
from sm_events.registration import args
from sm_events.registration.counters import SEAT, lock_counters, recount

__all__ = ["release", "release_target"]


async def release(db: Any, *, tenant_id: str, provider: str, holders: Sequence[str]) -> int:
    """Take these holders' seats back; the number freed. Idempotent and exact: a holder that holds
    no seat (or never did, or whose seat is another provider's) frees nothing, so a seat is never
    freed twice and never someone else's."""
    who = args.text(provider, "provider", maximum=constants.REGISTRATION_PROVIDER_MAX)
    wanted = args.holders(holders, maximum=constants.SEAT_RELEASE_MAX)
    stamp = utcnow()
    with tenant_scope(tenant_id) as tenant:
        held = (
            await db.execute(
                select(SEAT.c.event_id, SEAT.c.occurrence_key).where(
                    SEAT.c.tenant_id == tenant,
                    SEAT.c.provider == who,
                    SEAT.c.holder.in_(wanted),
                )
            )
        ).all()
        if not held:
            return 0
        counter_ids = await lock_counters(db, tenant, sorted({(e, k) for e, k in held}))
        freed = await db.execute(
            delete(SEAT).where(
                SEAT.c.tenant_id == tenant, SEAT.c.provider == who, SEAT.c.holder.in_(wanted)
            )
        )
        await recount(db, tenant, counter_ids, stamp)
        mark_written(db)
        return int(freed.rowcount or 0)


async def release_target(db: Any, *, tenant_id: str, provider: str, target: str) -> int:
    """Take back every seat of a target (its form was deleted); the number freed."""
    who = args.text(provider, "provider", maximum=constants.REGISTRATION_PROVIDER_MAX)
    what = args.text(target, "target", maximum=constants.REGISTRATION_TARGET_MAX)
    stamp = utcnow()
    with tenant_scope(tenant_id) as tenant:
        held = (
            await db.execute(
                select(SEAT.c.event_id, SEAT.c.occurrence_key)
                .where(SEAT.c.tenant_id == tenant, SEAT.c.provider == who, SEAT.c.target == what)
                .distinct()
            )
        ).all()
        if not held:
            return 0
        counter_ids = await lock_counters(db, tenant, sorted({(e, k) for e, k in held}))
        freed = await db.execute(
            delete(SEAT).where(
                SEAT.c.tenant_id == tenant, SEAT.c.provider == who, SEAT.c.target == what
            )
        )
        await recount(db, tenant, counter_ids, stamp)
        mark_written(db)
        return int(freed.rowcount or 0)
