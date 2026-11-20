"""Seat reconciliation: free the seats no live registration holds (PR 9).

A per-tenant step of the retention sweep. It catches a seat left by a path outside the hooks (a
record trashed before seats followed trashes, a host where events was installed later than
records, a crash between two statements) and repairs it **in one direction only**: it releases, it
never admits. A registration record without a seat (its event was hard-deleted, say) is left alone;
the availability read reports it ``unavailable``.

A seat is *held* when its holder is a live registration record: untrashed, of a registration type,
``pending`` or ``registered``. Anything else is released: a cancelled registration, a trashed one,
a holder nobody knows.

**Under the type locks.** Deciding that a record is not live and releasing its seat must not race a
restore, which flips the record live and admits the seat in one transaction. So every page runs
holding the registration types' locks (records' type lock, in key order, the first lock of the
global order documented in :mod:`.seats`), which every records writer takes first, and the events
locks follow inside ``release``. It is bounded (a page of seats per transaction, a cap on pages per
sweep) and idempotent.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any, Final

from sqlalchemy import select

from sm_records.contracts.public_submissions import KIND_REGISTRATION
from sm_records.core import events
from sm_records.core.tenancy import bound_tenant
from sm_records.models import tables_for
from sm_records.public_submissions.registration import seats
from sm_records.public_submissions.registration.status import SEATED
from sm_records.records.services._lock import lock_type
from sm_records.records.services.types import list_types

__all__ = ["MAX_PAGES", "PAGE", "page_released", "reconcile"]

logger = logging.getLogger(__name__)

PAGE: Final = 100
MAX_PAGES: Final = 50


def page_released(count: int) -> None:
    """Called with how many seats each page freed (a seam for the tests)."""


async def _live_holders(session: Any, types: list[Any], holders: list[str]) -> set[str]:
    """Of ``holders`` (hyphenated uuids), those that are live registrations in any of ``types``."""
    wanted = {uuid.UUID(h).hex: h for h in holders}
    live: set[str] = set()
    tenant = bound_tenant()
    for rtype in types:
        cls = tables_for(rtype).record
        stmt = select(cls).where(
            cls.uuid.in_(list(wanted)), cls.tenant_id == tenant, cls.type_id == rtype.id
        )  # the soft-delete filter hides the trashed: they are not live
        for record in (await session.execute(stmt)).scalars():
            if (record.data or {}).get(
                "sm_status"
            ) in SEATED:  # a pending registration holds no seat: its seat is drift
                live.add(wanted[record.uuid])
    return live


async def reconcile(factory: Callable[[], Any], *, page: int = PAGE, pages: int = MAX_PAGES) -> int:
    """Release the stale seats of the bound tenant; the number released. ``factory`` opens a session
    per page (finished through :func:`sm_records.core.events.commit`)."""
    if not seats.available():
        return 0
    released, after = 0, None
    for _ in range(pages):
        session = factory()
        try:
            types = [
                t
                for t in await list_types(session)
                if (t.public_submissions or {}).get("kind") == KIND_REGISTRATION
            ]
            for rtype in sorted(types, key=lambda t: t.key):
                await lock_type(session, rtype)
            held = await seats.integration().seat_holders(
                session, tenant_id=bound_tenant(), after=after, limit=page
            )
            if not held:
                await events.rollback(session)
                return released
            holders = [h.holder for h in held]
            live = await _live_holders(session, types, holders)
            stale = [h for h in holders if h not in live]
            try:
                freed = (
                    await seats.release(session, tenant_id=bound_tenant(), holders=stale)
                    if stale
                    else 0
                )
            except seats.SeatsBusy:  # events was busy: this page next sweep, nothing half-done
                await events.rollback(session)
                logger.info("records: seat reconciliation found events busy; next sweep")
                return released
            await events.commit(session)
        except BaseException:
            await events.rollback(session)
            raise
        finally:
            await session.close()
        released += freed
        page_released(freed)
        after = holders[-1]
        if len(held) < page:
            return released
    logger.info("records: seat reconciliation stopped after %d pages; the rest next sweep", pages)
    return released
