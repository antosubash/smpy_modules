"""Records' calls into events' seat contract, with the provider id fixed (PR 9).

The only code in records that imports ``sm_events.contracts.registration``; it is imported lazily
by :mod:`sm_records.public_submissions.registration.seats`. Every function takes the caller's
session and runs in the caller's transaction, under the lock order documented there.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sm_events.contracts import registration as seats

__all__ = [
    "EVENT_UNAVAILABLE",
    "PROVIDER_ID",
    "REGISTRATION_CLOSED",
    "REGISTRATION_FULL",
    "SEAT_RELEASE_MAX",
    "SeatsBusy",
    "admit",
    "describe",
    "format_instant",
    "release",
    "release_target",
    "seat_holders",
    "summaries",
]

PROVIDER_ID = "records:registration"
REGISTRATION_FULL = seats.REGISTRATION_FULL
REGISTRATION_CLOSED = seats.REGISTRATION_CLOSED
EVENT_UNAVAILABLE = seats.EVENT_UNAVAILABLE
SeatsBusy = seats.SeatsBusy
SEAT_RELEASE_MAX = seats.SEAT_RELEASE_MAX
format_instant = seats.format_instant


async def describe(
    db: Any,
    *,
    tenant_id: str,
    event_id: uuid.UUID | str,
    occurrence_key: str,
    target: str,
    locale: str,
    now: datetime | None = None,
) -> seats.Availability:
    return await seats.describe(
        db,
        tenant_id=tenant_id,
        event_id=event_id,
        occurrence_key=occurrence_key,
        provider=PROVIDER_ID,
        target=target,
        locale=locale,
        now=now,
    )


async def admit(
    db: Any,
    *,
    tenant_id: str,
    event_id: uuid.UUID | str,
    occurrence_key: str,
    target: str,
    holder: str,
    admin: bool = False,
    locale: str | None = None,
    now: datetime | None = None,
) -> seats.Admission:
    return await seats.admit(
        db,
        tenant_id=tenant_id,
        event_id=event_id,
        occurrence_key=occurrence_key,
        provider=PROVIDER_ID,
        target=target,
        holder=holder,
        admin=admin,
        locale=locale,
        now=now,
    )


async def release(db: Any, *, tenant_id: str, holders: Sequence[str]) -> int:
    return await seats.release(db, tenant_id=tenant_id, provider=PROVIDER_ID, holders=holders)


async def release_target(db: Any, *, tenant_id: str, target: str) -> int:
    return await seats.release_target(db, tenant_id=tenant_id, provider=PROVIDER_ID, target=target)


async def seat_holders(
    db: Any, *, tenant_id: str, after: str | None, limit: int
) -> list[seats.SeatRef]:
    return await seats.seat_holders(
        db, tenant_id=tenant_id, provider=PROVIDER_ID, after=after, limit=limit
    )


async def summaries(
    db: Any, *, tenant_id: str, refs: Sequence[tuple[uuid.UUID, str]], locale: str
) -> dict[tuple[uuid.UUID, str], seats.RegistrationEvent | None]:
    return await seats.summaries(
        db, tenant_id=tenant_id, provider=PROVIDER_ID, refs=refs, locale=locale
    )
