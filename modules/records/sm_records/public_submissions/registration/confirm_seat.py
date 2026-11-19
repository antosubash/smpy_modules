"""Taking the seat when an address is confirmed (a double opt-in form).

A submit creates a pending registration and holds **no** seat: so unconfirmed addresses can neither
squat seats nor lock newcomers out, and the public seat count does not move when an unknown address
submits. The seat is taken here, in the confirmation's own transaction and under the one global lock
order (the type lock and the row lock, then events' locks): the admit and the move to ``registered``
commit together or not at all.

If the event filled up (or closed) since the form was shown, the confirmation is refused with the
reason (409 ``registration_full`` / ``registration_closed``) and the record stays pending, to be
removed by the retention sweep after the pending TTL. That is told to someone who proved control of
the address by following its link, so it is no oracle. There is no waitlist.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import Record, RecordType
from sm_records.public_submissions.errors import SubmissionRefused
from sm_records.public_submissions.registration import seats
from sm_records.public_submissions.row_lock import lock_record

__all__ = ["take_seat"]

_EXPIRED = "this link has expired or is no longer valid; sign up again"
_REASON = {
    "registration_full": "this event is now fully booked",
    "registration_closed": "registration for this event is closed",
    "event_unavailable": "registration for this event is closed",
}


async def take_seat(
    db: AsyncSession, rtype: RecordType, record: Record, holds: Callable[[Record], bool]
) -> None:
    """Admit ``record``'s seat if it is still pending and the link still holds for it; else nothing
    (the caller's transition decides ``already_confirmed`` and expiry)."""
    try:
        row: Any = await lock_record(db, rtype, record)
    except NoResultFound:
        raise SubmissionRefused("link_expired", _EXPIRED) from None
    data = row.data or {}
    if row.is_deleted or not holds(row):
        raise SubmissionRefused("link_expired", _EXPIRED)
    if data.get("sm_status") != "pending":
        return
    if not seats.available():
        raise SubmissionRefused("registration_closed", _REASON["registration_closed"])
    given = await seats.integration().admit(
        db,
        tenant_id=rtype.tenant_id,
        event_id=str(data.get("sm_event_id") or ""),
        occurrence_key=str(data.get("sm_occurrence_key") or ""),
        target=rtype.key,
        holder=row.uuid,
    )
    if not given.admitted:
        code = given.code or "event_unavailable"
        known = code if code in _REASON else "registration_closed"
        raise SubmissionRefused(known, _REASON[known])
