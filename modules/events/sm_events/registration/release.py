"""Release: take seats back, exactly and idempotently (see :mod:`sm_events.registration.seats`).

**Invariant: within a transaction, counter locks are only ever acquired in ascending id order**
(the order ``admit`` and every other writer uses), so no two seat writers can wait on each other in
a cycle.

**Lock first, then act on exactly what is locked.** A release reads which occurrences its seats
are at, locks those counters (ascending), deletes only seats *at those occurrences* (returning
what it deleted) and recounts exactly the counters it locked while still holding them. A seat
admitted concurrently at another occurrence is not under a lock we hold, so the delete cannot touch
it; the next round finds it. If that occurrence's counter sorts **before** one already locked, it
is never locked out of order: the whole attempt (one SAVEPOINT) is rolled back, which releases its
row locks, and restarted locking the union of occurrences in ascending order from the start. At
most ``RESTARTS`` restarts; if seats keep arriving below, :class:`SeatsBusy` (a retryable 409,
documented on the contract) is raised and nothing has changed. A seat at an occurrence with no
counter row is never touched (reconciliation owns it). On SQLite there are no row locks and the
code path is identical (the savepoint is cheap and the ordering check is plain arithmetic).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from simple_module_db import mark_written
from sqlalchemy import delete, select, tuple_

from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.errors_registration import SeatsBusy
from sm_events.core.tenancy import tenant_scope
from sm_events.registration import args
from sm_events.registration.counters import COUNT, SEAT, lock_counters, recount

__all__ = ["release", "release_target"]

ROUNDS = 5
RESTARTS = 5
_CHUNK = 200


class _Restart(Exception):  # noqa: N818 - control flow
    def __init__(self, pairs: set[tuple[Any, str]]) -> None:
        super().__init__()
        self.pairs = pairs


async def _ids(db: Any, tenant: str, pairs: list[tuple[Any, str]]) -> dict[tuple[Any, str], int]:
    """Counter ids of these occurrences, **without locking**: to see the order before acquiring."""
    found: dict[tuple[Any, str], int] = {}
    for start in range(0, len(pairs), _CHUNK):
        rows = await db.execute(
            select(COUNT.c.id, COUNT.c.event_id, COUNT.c.occurrence_key).where(
                COUNT.c.tenant_id == tenant,
                tuple_(COUNT.c.event_id, COUNT.c.occurrence_key).in_(pairs[start : start + _CHUNK]),
            )
        )
        found.update({(e, k): i for i, e, k in rows.all()})
    return found


async def _attempt(
    db: Any, tenant: str, match: tuple[Any, ...], known: set[tuple[Any, str]], stamp: Any
) -> int:
    """One pass in a savepoint: lock ``known`` first, then what appears; :class:`_Restart` (the
    savepoint rolled back) when something appears below a lock already held."""
    seen: set[tuple[Any, str]] = set()
    freed, top = 0, 0
    async with db.begin_nested():
        pending = sorted(known, key=str)
        for _ in range(ROUNDS):
            if not pending:
                stmt = select(SEAT.c.event_id, SEAT.c.occurrence_key).where(
                    SEAT.c.tenant_id == tenant, *match
                )
                if seen:
                    stmt = stmt.where(
                        tuple_(SEAT.c.event_id, SEAT.c.occurrence_key).not_in(list(seen))
                    )
                pending = sorted({(e, k) for e, k in (await db.execute(stmt.distinct())).all()})
                if not pending:
                    return freed
            ids = await _ids(db, tenant, pending)
            if ids and min(ids.values()) < top:
                raise _Restart(seen | set(pending))
            ordered = sorted(ids, key=ids.__getitem__)
            seen.update(pending)
            for start in range(0, len(ordered), _CHUNK):
                locked = await lock_counters(db, tenant, ordered[start : start + _CHUNK])
                if not locked:
                    continue
                top = max(top, max(i for i, _, _ in locked))
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
            pending = []
        # the rounds are spent: anything still unseen restarts with it known, or we give up below
        rest = await db.execute(
            select(SEAT.c.event_id, SEAT.c.occurrence_key)
            .where(
                SEAT.c.tenant_id == tenant,
                *match,
                tuple_(SEAT.c.event_id, SEAT.c.occurrence_key).not_in(list(seen)),
            )
            .distinct()
        )
        left = {(e, k) for e, k in rest.all()}
        if left:
            raise _Restart(seen | left)
    return freed


async def _free(db: Any, tenant: str, *match: Any) -> int:
    """Delete the seats matching ``match`` under counters held in ascending order; the number."""
    stamp = utcnow()
    known: set[tuple[Any, str]] = set()
    for _ in range(RESTARTS + 1):
        try:
            freed = await _attempt(db, tenant, match, known, stamp)
        except _Restart as again:
            if again.pairs == known:  # no progress: the set did not grow, so it will not settle
                raise SeatsBusy from None
            known = again.pairs
            continue
        mark_written(db)
        return freed
    raise SeatsBusy


async def release(db: Any, *, tenant_id: str, provider: str, holders: Sequence[str]) -> int:
    """Take these holders' seats back; the number freed. Idempotent and exact: a holder that holds
    no seat (or never did, or whose seat is another provider's) frees nothing, so a seat is never
    freed twice and never someone else's. :class:`SeatsBusy` (retry) if it cannot settle."""
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
