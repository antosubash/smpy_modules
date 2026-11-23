"""Cancelling a registration, and freeing its seat in the same transaction (PR 9).

Three callers, one function: the registrant's cancel link, the admin action and (through the
records trash paths) nobody else: a trash or a purge releases the seat through
:mod:`.seats`' hooks. The record is **kept** as ``cancelled`` (so the organiser sees who
cancelled), its nonce rotates (every link minted before dies, the confirm link included), and its
seat is released exactly once.

Lock order: the type lock and the row lock first (``transition(lock=True)``, as every unsubscribe
does), then events' counter row (``release``): the one global order documented in
:mod:`sm_records.public_submissions.registration.seats`. An occurrence that has started cannot be
cancelled (it is the same answer: nothing changes).
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.public_submissions import KIND_REGISTRATION
from sm_records.core.settings import RecordsSettings
from sm_records.models import Record, RecordType
from sm_records.public_submissions import links
from sm_records.public_submissions.registration import seats
from sm_records.public_submissions.registration import start as start_module
from sm_records.public_submissions.registration.status import CANCELLED, LIVE
from sm_records.public_submissions.transition import Change, transition
from sm_records.records.services import records as record_service
from sm_records.records.services._common import utcnow
from sm_records.records.services.errors import NotFound
from sm_records.records.services.types import get_type

__all__ = ["CANCELLED", "cancel", "cancel_by_link"]


def _now() -> datetime:
    return utcnow()


async def cancel(
    db: AsyncSession,
    rtype: RecordType,
    record: Record,
    *,
    settings: RecordsSettings,
    now: datetime | None = None,
    still: Callable[[Record], bool] | None = None,
) -> bool:
    """Cancel ``record`` if it is a live registration whose occurrence has not started (and, with
    ``still``, that the caller's claim still holds for); whether *this* call cancelled it."""
    stamp = now or _now()
    # Events' resolved start (a moved occurrence), not the snapshot taken at submit.
    start = await start_module.resolved_start(db, rtype.tenant_id, record.data or {})

    def derive(row: Record) -> Change | None:
        data = row.data or {}
        if (
            row.is_deleted
            or data.get("sm_status") not in LIVE
            or (start is not None and start <= stamp)
        ):
            return None
        if still is not None and not still(row):
            return None
        return {
            "sm_status": CANCELLED,
            "sm_cancelled_at": stamp,
            "sm_nonce": secrets.token_hex(16),
        }, None

    outcome = await transition(db, rtype, record, derive, settings=settings, lock=True)
    if outcome.wrote and seats.available():
        await seats.release(db, tenant_id=rtype.tenant_id, holders=[record.uuid])
    return outcome.wrote


async def cancel_by_link(
    db: AsyncSession, secret: str, link: links.Link, settings: RecordsSettings
) -> None:
    """The registrant's link. Silent whatever it names: the caller answers the same ``200``."""
    try:
        rtype = await get_type(db, link.type_key)
        if (rtype.public_submissions or {}).get("kind") != KIND_REGISTRATION:
            return
        record = await record_service.get_record(db, rtype, link.uuid)

        def holds(row: Record) -> bool:
            return links.matches(secret, link, (row.data or {}).get("sm_nonce"))

        await cancel(db, rtype, record, settings=settings, still=holds)
    except NotFound:  # unknown, purged since the lookup: answered as any other
        return
