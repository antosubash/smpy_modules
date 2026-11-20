"""Seats at an event, for the module that owns the people who register (records).

**Who owns what.** Events owns the seats (the capacity, the window, the counter and one seat row
per holder) and the rule; the provider owns the registrants. A seat names its holder by an opaque
id and nothing else. This contract is what the provider calls; events never imports the provider
(it learns that one exists through :mod:`sm_events.contracts.extensions`).

**Transaction.** Every call here runs in the caller's session and transaction, pins the tenant it
is given (an unbound session works; naming another tenant than the bound one raises
``TenantIsolationError``), puts the tenant in every Core statement, never commits and flags the
session as written. A malformed argument raises ``ValueError`` before any statement.

**Lock order**, for a caller that takes locks of its own: its own locks first (records: the type
lock), then this contract's, which are always the event row (``FOR SHARE``, ``admit`` only), then
the occurrence's counter row, then the seat rows. Nothing here calls back into the caller, so no
cycle can form. A caller must not hold a seat lock while it waits for something else.

**Retry.** ``release`` and ``release_target`` may raise :class:`SeatsBusy` (a 409, code
``seats_busy``): seats kept arriving below the counters they hold, so they could not settle their
locks in ascending order within a bounded number of restarts. Nothing was changed; answer "try
again" and never 500. Within a transaction, counter locks are only ever acquired in ascending id
order.

**Who may see what.** :func:`describe` and :func:`summaries` answer only for a public, published
event with this provider's registration, and for anything else say the same "unavailable" /
``None`` the public pages say; they return counts at most, never a name or an address.
:func:`seat_holders` returns the provider's own opaque ids, paged: use it only to reconcile.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from sm_events.core import constants
from sm_events.core.errors_registration import SeatsBusy
from sm_events.registration import availability as _availability
from sm_events.registration import release as _release
from sm_events.registration import seat_reads as _reads
from sm_events.registration import seats as _seats
from sm_events.registration import summaries as _summaries
from sm_events.registration.availability import Availability, RegistrationEvent
from sm_events.registration.seat_reads import SeatRef
from sm_events.registration.seats import Admission

__all__ = [
    "EVENT_UNAVAILABLE",
    "REGISTRATION_CLOSED",
    "REGISTRATION_FULL",
    "SEAT_RELEASE_MAX",
    "Admission",
    "Availability",
    "RegistrationEvent",
    "SeatRef",
    "SeatsBusy",
    "admit",
    "describe",
    "release",
    "release_target",
    "seat_holders",
    "summaries",
]

SEAT_RELEASE_MAX = constants.SEAT_RELEASE_MAX
"""How many holders one ``release`` call takes: a caller with more splits its calls."""
_RETRYABLE = frozenset({"40P01", "40001"})  # deadlock detected, serialization failure


async def _guarded[T](db: AsyncSession, call: Callable[[], Awaitable[T]]) -> T:
    """Run a write in a savepoint of its own: a database deadlock or serialization failure inside
    it is rolled back to the savepoint and re-raised as :class:`SeatsBusy` (retry), so no path can
    surface one as a 500. The transaction stays usable; the caller rolls back or retries."""
    try:
        async with db.begin_nested():
            return await call()
    except DBAPIError as exc:
        code = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
        if code in _RETRYABLE:
            raise SeatsBusy from exc
        raise


REGISTRATION_FULL = constants.REGISTRATION_FULL
REGISTRATION_CLOSED = constants.REGISTRATION_CLOSED
EVENT_UNAVAILABLE = constants.EVENT_UNAVAILABLE


async def describe(
    db: AsyncSession,
    *,
    tenant_id: str,
    event_id: uuid.UUID | str,
    occurrence_key: str,
    provider: str,
    target: str,
    locale: str,
    now: datetime | None = None,
) -> Availability:
    """What one occurrence offers: ``unavailable`` (one answer for everything not public or not
    this provider's), ``cancelled``, ``closed``, ``not_open_yet``, ``full`` or ``open``. Seats left
    only when the event shows them."""
    return await _availability.describe(
        db,
        tenant_id=tenant_id,
        event_id=event_id,
        occurrence_key=occurrence_key,
        provider=provider,
        target=target,
        locale=locale,
        now=now,
    )


async def admit(
    db: AsyncSession,
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
    """Give ``holder`` one seat at one occurrence, or refuse with ``registration_full``,
    ``registration_closed`` or ``event_unavailable``. Never oversells, idempotent per holder, and
    its seat exists exactly when the caller's transaction commits. ``admin=True`` skips the window
    and "already started" (a restore), never availability, cancellation or capacity."""
    return await _guarded(
        db,
        lambda: _seats.admit(
            db,
            tenant_id=tenant_id,
            event_id=event_id,
            occurrence_key=occurrence_key,
            provider=provider,
            target=target,
            holder=holder,
            admin=admin,
            now=now,
            locale=locale,
        ),
    )


async def release(
    db: AsyncSession, *, tenant_id: str, provider: str, holders: Sequence[str]
) -> int:
    """Free these holders' seats (1 to 1,000); the number freed. Idempotent: an unknown holder is
    nothing, and a seat is never freed twice or by another provider."""
    return await _guarded(
        db,
        lambda: _release.release(db, tenant_id=tenant_id, provider=provider, holders=holders),
    )


async def release_target(db: AsyncSession, *, tenant_id: str, provider: str, target: str) -> int:
    """Free every seat of a target (its form was deleted); the number freed."""
    return await _guarded(
        db,
        lambda: _release.release_target(db, tenant_id=tenant_id, provider=provider, target=target),
    )


async def seat_holders(
    db: AsyncSession, *, tenant_id: str, provider: str, after: str | None, limit: int
) -> list[SeatRef]:
    """A page (1 to 500) of ``provider``'s seats by holder, strictly after ``after``."""
    return await _reads.seat_holders(
        db, tenant_id=tenant_id, provider=provider, after=after, limit=limit
    )


async def summaries(
    db: AsyncSession,
    *,
    tenant_id: str,
    provider: str,
    refs: Sequence[tuple[uuid.UUID, str]],
    locale: str,
) -> dict[tuple[uuid.UUID, str], RegistrationEvent | None]:
    """The public facts of up to 200 ``(event_id, occurrence_key)`` references, ``None`` for any
    that ``describe`` would call unavailable. A fixed number of statements."""
    return await _summaries.summaries(
        db, tenant_id=tenant_id, provider=provider, refs=refs, locale=locale
    )
