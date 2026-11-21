"""Seats: admit under the capacity, release exactly, and a counter that is always the seats' count.

Everything here runs in the **caller's session and transaction** and never commits (the caller's
transaction finishes the write; this module flags the session as written, because the statements
are Core DML on bare tables, which the framework would otherwise roll back as a read). Every
statement is a Core statement, so each carries its own ``tenant_id``.

**The lock order**, the same in every path (documented once, here):

1. the event row, ``FOR SHARE`` (admit only), so a change that unpublishes, cancels or trashes the
   event, which takes the row exclusively, waits for the admit to end and the admit never seats
   somebody in an event that is gone;
2. the occurrence's counter row, ``FOR UPDATE`` (several: in ascending ``id``), taken **before** any
   seat row is touched and held to the end of the transaction. It serialises every seat change of
   one occurrence, so what is counted afterwards is exact: the next statement of a transaction
   that waited for it has a fresh snapshot and sees what the winner committed;
3. the seat rows.

A caller that takes locks of its own takes them *before* step 1 (records: its type lock, then
events), and nothing here ever calls back into another module, so no cycle exists.

**Why a counter row and seat rows.** The counter is the lock target and a cheap read; the seat rows
(unique per ``(tenant, provider, holder)``) make admit and release idempotent per holder and let the
counter be recomputed from the rows instead of adjusted: a release sets ``taken`` to the number of
seat rows, so a counter that drifted heals at the next change. SQLite has one writer at a time and
the caller's records lock already serialises there, so the row locks are no-ops on it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from simple_module_db import mark_written
from sqlalchemy import delete, select, update

from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.tenancy import tenant_scope
from sm_events.registration import args
from sm_events.registration.availability import Found, RegistrationEvent, lookup
from sm_events.registration.availability import registration_event as build_event
from sm_events.registration.counters import COUNT, SEAT, SEAT_KEY, insert_for, lock_counter
from sm_events.registration.release import release, release_target
from sm_events.registration.seat_reads import SeatRef, counts, seat_holders

__all__ = ["Admission", "SeatRef", "admit", "counts", "release", "release_target", "seat_holders"]


@dataclass(frozen=True)
class Admission:
    admitted: bool
    code: str | None
    """``None`` when admitted; else ``registration_full``, ``registration_closed`` or
    ``event_unavailable``."""
    event: RegistrationEvent | None
    """What a confirmation needs, only when admitted and the caller passed a ``locale``."""


def _refused(code: str) -> Admission:
    return Admission(False, code, None)


def _refusal(found: Found, now: datetime, *, admin: bool) -> str | None:
    """Why this occurrence cannot take a seat now, apart from being full. ``admin`` skips the
    window and "already started"; a cancelled occurrence is not available to anyone."""
    event, occurrence = found.event, found.occurrence
    if event.cancelled or occurrence.cancelled:
        return constants.REGISTRATION_CLOSED
    if admin:
        return None
    if (event.registration_closes_at and now >= event.registration_closes_at) or (
        now >= occurrence.start
    ):
        return constants.REGISTRATION_CLOSED
    if event.registration_opens_at and now < event.registration_opens_at:
        return constants.REGISTRATION_CLOSED
    return None


async def admit(
    db: Any,
    *,
    tenant_id: str,
    event_id: uuid.UUID | str,
    occurrence_key: str,
    provider: str,
    target: str,
    holder: str,
    admin: bool = False,
    now: datetime | None = None,
    locale: str | None = None,
) -> Admission:
    """Give ``holder`` a seat at one occurrence, or say why not. Idempotent per holder: one that
    already holds a seat *here* is admitted again and counted once; one seated elsewhere is refused
    ``event_unavailable`` (a seat never moves).

    ``admin=True`` (a restore by an organiser) skips the window and "already started", never
    availability, cancellation or capacity. With ``locale`` an admitted answer carries the event."""
    eid = args.event_id(event_id)
    key = args.occurrence_key(occurrence_key)
    who = args.text(provider, "provider", maximum=constants.REGISTRATION_PROVIDER_MAX)
    what = args.text(target, "target", maximum=constants.REGISTRATION_TARGET_MAX)
    seat_holder = args.holder(holder)
    if not isinstance(admin, bool):
        raise ValueError("admin must be a bool")
    lang = None if locale is None else args.text(locale, "locale", maximum=constants.LOCALE_MAX)
    stamp = now or utcnow()
    with tenant_scope(tenant_id) as tenant:
        found = await lookup(db, eid, key, who, what, lock=True)
        if found is None:
            return _refused(constants.EVENT_UNAVAILABLE)
        if (why := _refusal(found, stamp, admin=admin)) is not None:
            return _refused(why)
        await lock_counter(db, tenant, eid, key, stamp)
        mark_written(db)
        inserted = (
            await db.execute(
                insert_for(db)(SEAT)
                .values(
                    tenant_id=tenant,
                    event_id=eid,
                    occurrence_key=key,
                    provider=who,
                    target=what,
                    holder=seat_holder,
                    created_at=stamp,
                )
                .on_conflict_do_nothing(index_elements=SEAT_KEY)
                .returning(SEAT.c.id)
            )
        ).scalar_one_or_none()
        if inserted is None:  # this holder already holds a seat: here (idempotent) or elsewhere
            held = (
                await db.execute(
                    select(SEAT.c.event_id, SEAT.c.occurrence_key).where(
                        SEAT.c.tenant_id == tenant,
                        SEAT.c.provider == who,
                        SEAT.c.holder == seat_holder,
                    )
                )
            ).first()
            if held is None or (held[0], held[1]) != (eid, key):
                return _refused(constants.EVENT_UNAVAILABLE)
        else:
            capacity = found.event.registration_capacity
            took = await db.execute(
                update(COUNT)
                .where(
                    COUNT.c.tenant_id == tenant,
                    COUNT.c.event_id == eid,
                    COUNT.c.occurrence_key == key,
                    *([] if capacity is None else [COUNT.c.taken < capacity]),
                )
                .values(taken=COUNT.c.taken + 1, updated_at=stamp)
                .returning(COUNT.c.taken)
            )
            if took.scalar_one_or_none() is None:
                await db.execute(delete(SEAT).where(SEAT.c.id == inserted))
                return _refused(constants.REGISTRATION_FULL)
        event = None if lang is None else await build_event(db, found.event, found.occurrence, lang)
        return Admission(True, None, event)
