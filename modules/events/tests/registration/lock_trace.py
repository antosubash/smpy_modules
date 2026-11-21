"""Record every counter id a transaction locks, and fail on a descending acquisition.

The invariant of the seat code: *within a transaction, counter locks are only ever acquired in
ascending id order.* :func:`trace` wraps the two lock primitives and checks it per session (a
session here is one transaction); the concurrency tests install it.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sm_events.registration import counters, release, seats


class OutOfOrderError(AssertionError):
    """A counter lock was acquired below one already held in the same transaction."""


class Trace:
    """Locks are kept on the session itself (``info``), so a recycled ``id()`` cannot mix two."""

    def __init__(self) -> None:
        self.by_session: dict[int, list[int]] = defaultdict(list)

    def note(self, db: Any, ids: list[int]) -> None:
        held = db.info.setdefault("lock_trace", [])
        for ident in ids:
            if held and ident < max(held):
                raise OutOfOrderError(f"counter {ident} locked after {max(held)} in one txn")
            held.append(ident)
            self.by_session[id(db)] = held

    def forget(self, db: Any) -> None:
        db.info.pop("lock_trace", None)


def install(monkeypatch) -> Trace:
    trace = Trace()
    real_many, real_one = counters.lock_counters, counters.lock_counter

    async def many(db, tenant, keys):
        rows = await real_many(db, tenant, keys)
        trace.note(db, [row[0] for row in rows])
        return rows

    async def one(db, tenant, event_id, key, now):
        ident = await real_one(db, tenant, event_id, key, now)
        trace.note(db, [ident])
        return ident

    real_attempt = release._attempt

    async def attempt(db, *args):
        try:
            return await real_attempt(db, *args)
        except release._Restart:
            trace.forget(db)  # the savepoint was rolled back: its row locks are gone
            raise

    monkeypatch.setattr(release, "_attempt", attempt)
    monkeypatch.setattr(counters, "lock_counters", many)
    monkeypatch.setattr(release, "lock_counters", many)
    monkeypatch.setattr(counters, "lock_counter", one)
    monkeypatch.setattr(seats, "lock_counter", one)
    return trace
