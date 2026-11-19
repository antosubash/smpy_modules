"""Release: take seats back, exactly and idempotently (see :mod:`sm_events.registration.seats`).

**Lock first, then act on exactly what is locked.** The lock order is the one ``admit`` uses
(counter rows before seat rows, counters in ascending id). A release reads which occurrences its
seats are at, locks those counters, and deletes only seats *at those occurrences*, returning what
it deleted; it then recomputes exactly the counters it locked, from the seat rows, while still
holding them. A seat admitted concurrently at another occurrence is not under a lock we hold, so
the delete cannot touch it: the next round (bounded by ``ROUNDS``) sees it, locks its counter and
frees it, or it is left alone and its counter stays right. A seat at an occurrence with no counter
row is never touched either (reconciliation owns it).

A later round can lock a counter with a lower id than one already held. The only transaction that
could wait on us while holding such a counter is an ``admit`` of a holder whose seat we just
deleted, at a different occurrence: a refused call (a seat never moves). If it ever happens
Postgres aborts one side with a deadlock error; nothing hangs and nothing is half-counted.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from simple_module_db import mark_written
from sqlalchemy import delete, select, tuple_

from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.tenancy import tenant_scope
from sm_events.registration import args
from sm_events.registration.counters import SEAT, lock_counters, recount

__all__ = ["release", "release_target"]

ROUNDS = 5
_CHUNK = 200


async def _free(db: Any, tenant: str, *match: Any) -> int:
    """Delete the seats matching ``match`` under counters we hold; the number deleted."""
    stamp = utcnow()
    seen: set[tuple[Any, str]] = set()
    freed = 0
    for _ in range(ROUNDS):
        stmt = select(SEAT.c.event_id, SEAT.c.occurrence_key).where(
            SEAT.c.tenant_id == tenant, *match
        )
        if seen:
            stmt = stmt.where(tuple_(SEAT.c.event_id, SEAT.c.occurrence_key).not_in(list(seen)))
        pairs = sorted({(e, k) for e, k in (await db.execute(stmt.distinct())).all()})
        if not pairs:
            break
        seen.update(pairs)
        for start in range(0, len(pairs), _CHUNK):
            locked = await lock_counters(db, tenant, pairs[start : start + _CHUNK])
            if not locked:
                continue
            gone = await db.execute(
                delete(SEAT)
                .where(
                    SEAT.c.tenant_id == tenant,
                    *match,
                    tuple_(SEAT.c.event_id, SEAT.c.occurrence_key).in_(
                        [(e, k) for _, e, k in locked]
                    ),
                )
                .returning(SEAT.c.event_id, SEAT.c.occurrence_key)
            )
            freed += len(gone.all())
            await recount(db, tenant, [i for i, _, _ in locked], stamp)
    mark_written(db)
    return freed


async def release(db: Any, *, tenant_id: str, provider: str, holders: Sequence[str]) -> int:
    """Take these holders' seats back; the number freed. Idempotent and exact: a holder that holds
    no seat (or never did, or whose seat is another provider's) frees nothing, so a seat is never
    freed twice and never someone else's."""
    who = args.text(provider, "provider", maximum=constants.REGISTRATION_PROVIDER_MAX)
    wanted = args.holders(holders, maximum=constants.SEAT_RELEASE_MAX)
    with tenant_scope(tenant_id) as tenant:
        return await _free(db, tenant, SEAT.c.provider == who, SEAT.c.holder.in_(wanted))


async def release_target(db: Any, *, tenant_id: str, provider: str, target: str) -> int:
    """Take back every seat of a target (its form was deleted); the number freed."""
    who = args.text(provider, "provider", maximum=constants.REGISTRATION_PROVIDER_MAX)
    what = args.text(target, "target", maximum=constants.REGISTRATION_TARGET_MAX)
    with tenant_scope(tenant_id) as tenant:
        return await _free(db, tenant, SEAT.c.provider == who, SEAT.c.target == what)
