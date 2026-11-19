"""The one seam between a record's life and its seat (PR 9).

Every path that trashes, restores or purges a record of a registration type calls the matching
hook here, **inside the same transaction and after the records locks it already holds**, so a
record and its seat change together or not at all. The global lock order, in one line, for every
path (submit, cancel, trash, restore, purge, retention, reconciliation)::

    records address/opt-in locks -> records type lock -> records row lock
        -> events event row (FOR SHARE) -> events counter row -> events seat rows

and events never takes a records lock (its calls into records, the provider's, run on their own
connection and only read). Each hook is a no-op unless the type's kind is ``registration``, and,
without the events module, a trash or purge just carries on (nothing holds a seat to free).

The events integration is imported inside each function: nothing of events is imported with this
module.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Sequence
from typing import Any

from sm_records.contracts.public_submissions import KIND_REGISTRATION
from sm_records.public_submissions.errors import SubmissionRefused
from sm_records.records.services.errors import Conflict

__all__ = [
    "SeatsBusy",
    "available",
    "integration",
    "is_registration",
    "on_purged",
    "on_restored",
    "on_trashed",
    "on_type_purged",
    "release",
    "release_target",
]

logger = logging.getLogger(__name__)
_WARNED = {"missing": False}


def is_registration(rtype: Any) -> bool:
    return ((getattr(rtype, "public_submissions", None) or {}).get("kind")) == KIND_REGISTRATION


def integration() -> Any:
    """The events integration module; ``ImportError`` when events is not installed."""
    return importlib.import_module("sm_records.integrations.events.registration")


def available() -> bool:
    """Whether the events module (and so seats) is installed."""
    try:
        integration()
    except ImportError:
        if not _WARNED["missing"]:
            _WARNED["missing"] = True
            logger.info("records: the events module is not installed; registrations hold no seats")
        return False
    return True


_LIVE = ("pending", "registered")


class SeatsBusy(Conflict):
    """Events could not settle a release within its bounded restarts (``seats_busy``): nothing was
    changed, and the answer is "try again" (a 409), never a 500."""

    code = "seats_busy"


async def release(db: Any, *, tenant_id: str, holders: Sequence[str]) -> int:
    """Free these holders' seats; :class:`SeatsBusy` (the request rolls back) if events is busy."""
    module = integration()
    try:
        return await module.release(db, tenant_id=tenant_id, holders=holders)
    except module.SeatsBusy as exc:
        raise SeatsBusy("the seats are busy; try again") from exc


async def release_target(db: Any, *, tenant_id: str, target: str) -> int:
    module = integration()
    try:
        return await module.release_target(db, tenant_id=tenant_id, target=target)
    except module.SeatsBusy as exc:
        raise SeatsBusy("the seats are busy; try again") from exc


async def on_trashed(db: Any, pairs: Sequence[tuple[Any, Any]]) -> None:
    """A record of a registration type went to the trash (single, cascade, bulk, spam, retention):
    its seat is freed, in the trashing transaction. Cancelled records hold none (a release of a
    seat that is not there is nothing)."""
    held: dict[str, list[str]] = {}
    for record, rtype in pairs:
        if is_registration(rtype):
            held.setdefault(rtype.tenant_id, []).append(record.uuid)
    if not held or not available():
        return
    for tenant, holders in held.items():
        await release(db, tenant_id=tenant, holders=holders)


async def on_restored(db: Any, rtype: Any, record: Any) -> None:
    """A trashed registration is coming back: it takes a seat again **only if one is free** (an
    organiser's restore skips the window, never the capacity or the event's availability), else the
    restore is refused (409 ``registration_full`` / ``event_unavailable``) and nothing changes. A
    cancelled registration holds no seat and needs none."""
    if not is_registration(rtype):
        return
    data = record.data or {}
    if data.get("sm_status") not in _LIVE:
        return
    if not available():
        raise SubmissionRefused("event_unavailable", "the events module is not installed")
    given = await integration().admit(
        db,
        tenant_id=rtype.tenant_id,
        event_id=str(data.get("sm_event_id") or ""),
        occurrence_key=str(data.get("sm_occurrence_key") or ""),
        target=rtype.key,
        holder=record.uuid,
        admin=True,
    )
    if not given.admitted:
        code = given.code or "event_unavailable"
        raise SubmissionRefused(code, "this registration cannot be restored: " + code)


async def on_purged(db: Any, rtype: Any, uuids: Sequence[str]) -> None:
    """Records of a registration type are being purged: free their seats again (idempotent: a seat
    freed at the trash is not freed twice; one left by a record trashed before seats followed
    trashes, or on a host that had no events then, goes now)."""
    if is_registration(rtype) and uuids and available():
        await release(db, tenant_id=rtype.tenant_id, holders=list(uuids))


async def on_type_purged(db: Any, rtype: Any) -> None:
    """A registration type is being deleted with all its records: free every seat of its form."""
    if is_registration(rtype) and available():
        await release_target(db, tenant_id=rtype.tenant_id, target=rtype.key)
