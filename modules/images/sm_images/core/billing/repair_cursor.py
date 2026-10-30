"""The repair's scan cursor (``images_billing_cursor``): bounded laps.

A lap scans a tenant's done ops with ``last_op_id < id <= lap_end``, a page
(``billing_repair.CAP``) per call. ``lap_end`` is the tenant's highest op id
when the lap began, persisted once: ops written during the lap wait for the
next one, so a tenant whose ops keep arriving still finishes every lap and
comes back to the ops the last one deferred. A page shorter than ``CAP`` -
empty, or thinned by gaps and swept rows, or ended by a deleted top row -
ends the lap; the cursor goes back to ``(0, NULL)`` and the next call starts
a new one.

**Moved by compare-and-set.** Every write names the state it was decided from
(``last_op_id`` *and* ``lap_end``) and changes nothing when another repair
moved the cursor since: two concurrent repairs scan the same page (their
decisions are serialised per image), and only one moves the cursor on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from sm_images.models import BillingOp, BillingRepairCursor

__all__ = ["Lap", "begin", "move", "read"]


@dataclass(frozen=True)
class Lap:
    """A cursor state as read: ``end`` ``None`` between laps."""

    last: int = 0
    end: int | None = None
    stored: bool = False
    """Whether the tenant has a cursor row yet."""


async def read(db: Any, tenant: str) -> Lap:
    stmt = select(BillingRepairCursor.last_op_id, BillingRepairCursor.lap_end).where(
        BillingRepairCursor.tenant_id == tenant
    )
    row = (await db.execute(stmt)).first()
    return Lap() if row is None else Lap(int(row[0]), row[1], True)


async def begin(factory: Any, tenant: str) -> Lap | None:
    """The lap to scan now: the one in progress, or a new one up to the
    tenant's highest op id (persisted). ``None`` when it has no ops."""
    async with factory() as db:
        lap = await read(db, tenant)
        top = (
            await db.execute(select(func.max(BillingOp.id)).where(BillingOp.tenant_id == tenant))
        ).scalar_one_or_none()
        await db.rollback()
    if lap.end is not None:
        return lap
    if top is None:
        return None
    if await move(factory, tenant, lap, lap.last, int(top)):
        return Lap(lap.last, int(top), True)
    async with factory() as db:  # another repair began it first: use its lap
        again = await read(db, tenant)
        await db.rollback()
    return again if again.end is not None else None


async def move(factory: Any, tenant: str, seen: Lap, last: int, end: int | None) -> bool:
    """Set the cursor to ``(last, end)`` only if it is still ``seen``; whether
    this call moved it."""
    async with factory() as db:
        if not seen.stored:
            db.add(BillingRepairCursor(tenant_id=tenant, last_op_id=last, lap_end=end))
            try:
                await finalize_session(db)
            except IntegrityError:  # a concurrent repair created it
                return False
            return True
        same_end = (
            BillingRepairCursor.lap_end.is_(None)
            if seen.end is None
            else BillingRepairCursor.lap_end == seen.end
        )
        moved = await db.execute(
            update(BillingRepairCursor)
            .where(
                BillingRepairCursor.tenant_id == tenant,
                BillingRepairCursor.last_op_id == seen.last,
                same_end,
            )
            .values(last_op_id=last, lap_end=end)
            .returning(BillingRepairCursor.id)
            .execution_options(synchronize_session=False)
        )
        won = moved.first() is not None
        await finalize_session(db)
    return won
