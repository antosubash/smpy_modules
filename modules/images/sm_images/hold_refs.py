"""Hold ownership (``images_hold_ref``): installing and releasing a hold are
compare-and-sets on one row, so they can never both win.

* :func:`installed` - a hold an image names from now on (ingest, a fenced
  publication), written with the image row; :func:`orphan` - the hold it named
  before, in the same transaction.
* :func:`reserved` - a rehold's replacement, recorded before it is committed.
* :func:`install` - ``reserved|orphan → installed``, in the transaction that
  writes the replacement onto the image.
* :func:`release` - ``reserved|orphan|releasing → releasing`` in a short
  transaction of its own; only the winner calls billing, then ``released``. An
  ``installed`` hold is never released (an image names it); a hold with no
  row (one that was never installed: a duplicate, a rolled-back completion)
  is claimed by inserting its row as ``releasing``. ``releasing`` may be
  re-entered: a releaser that died after winning is retried, and billing's
  ``release`` is idempotent. A hold whose row reads ``released`` already
  counts as released: :func:`release` answers ``True`` without calling
  billing, so a releaser that died after the row committed ``released`` (but
  before it recorded that anywhere else) resumes instead of wedging.

Every statement names the tenant.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from sm_images.models import HoldRef
from sm_images.models.hold_ref import (
    REF_INSTALLED,
    REF_ORPHAN,
    REF_RELEASED,
    REF_RELEASING,
    REF_RESERVED,
)

__all__ = ["install", "installed", "orphan", "orphan_reserved", "release", "reserved"]

_SYNC = {"synchronize_session": False}


async def installed(db: Any, hold_id: str, image_id: uuid.UUID | None) -> None:
    """``hold_id`` is what ``image_id`` names now (a fresh hold: no row yet)."""
    await db.merge(HoldRef(hold_id=hold_id, image_id=image_id, state=REF_INSTALLED))


async def orphan(db: Any, tenant: str, hold_id: str | None) -> None:
    """The image no longer names ``hold_id``: it may be released."""
    if hold_id is None:
        return
    await db.execute(
        update(HoldRef)
        .where(
            HoldRef.hold_id == hold_id,
            HoldRef.tenant_id == tenant,
            HoldRef.state == REF_INSTALLED,
        )
        .values(state=REF_ORPHAN)
        .execution_options(**_SYNC)
    )


async def orphan_reserved(db: Any, tenant: str, hold_id: str) -> None:
    """A replacement nobody will install: ``reserved → orphan`` (releasable)."""
    await db.execute(
        update(HoldRef)
        .where(
            HoldRef.hold_id == hold_id,
            HoldRef.tenant_id == tenant,
            HoldRef.state == REF_RESERVED,
        )
        .values(state=REF_ORPHAN)
        .execution_options(**_SYNC)
    )


async def reserved(db: Any, tenant: str, hold_id: str, image_id: uuid.UUID | None) -> None:
    """A replacement not installed yet (kept as is when it has a row already:
    a replayed reservation)."""
    found = await db.execute(
        select(HoldRef.hold_id).where(HoldRef.hold_id == hold_id, HoldRef.tenant_id == tenant)
    )
    if found.first() is None:
        db.add(HoldRef(hold_id=hold_id, image_id=image_id, state=REF_RESERVED))
        await db.flush()


async def install(db: Any, tenant: str, hold_id: str) -> bool:
    """``reserved|orphan → installed``; ``False`` when a release got there first."""
    got = await db.execute(
        update(HoldRef)
        .where(
            HoldRef.hold_id == hold_id,
            HoldRef.tenant_id == tenant,
            HoldRef.state.in_((REF_RESERVED, REF_ORPHAN)),
        )
        .values(state=REF_INSTALLED)
        .returning(HoldRef.hold_id)
        .execution_options(**_SYNC)
    )
    return got.first() is not None


_WON, _GONE, _LOST = "won", "released", "lost"


async def _claim(factory: Any, tenant: str, hold_id: str) -> str:
    """:data:`_WON` (ours to release), :data:`_GONE` (released already) or
    :data:`_LOST` (an image names it)."""
    async with factory() as db:
        got = await db.execute(
            update(HoldRef)
            .where(
                HoldRef.hold_id == hold_id,
                HoldRef.tenant_id == tenant,
                HoldRef.state.in_((REF_RESERVED, REF_ORPHAN, REF_RELEASING)),
            )
            .values(state=REF_RELEASING)
            .returning(HoldRef.hold_id)
            .execution_options(**_SYNC)
        )
        won: str | None = _WON if got.first() is not None else _LOST
        if won == _LOST:
            state = (
                await db.execute(
                    select(HoldRef.state).where(
                        HoldRef.hold_id == hold_id, HoldRef.tenant_id == tenant
                    )
                )
            ).scalar_one_or_none()
            if state is None:  # never installed anywhere: ours to release
                db.add(HoldRef(hold_id=hold_id, image_id=None, state=REF_RELEASING))
                won = _WON
            elif state == REF_RELEASED:
                won = _GONE
        try:
            await finalize_session(db)
        except IntegrityError:  # a concurrent first claim inserted it: re-read
            won = None
    return await _claim(factory, tenant, hold_id) if won is None else won


async def release(
    factory: Any,
    tenant: str,
    hold_id: str,
    meter: Any,
    before: Callable[[], Awaitable[None]] | None = None,
) -> bool:
    """Release ``hold_id`` unless an image names it; ``False`` when one does,
    ``True`` once it is released (by this call or an earlier one). A hold
    billing does not know is released already. ``before`` (tests) runs between
    winning the row and calling billing."""
    from sm_billing.contracts.metering import HoldNotFound

    claimed = await _claim(factory, tenant, hold_id)
    if claimed != _WON:
        return claimed == _GONE
    if before is not None:
        await before()
    with contextlib.suppress(HoldNotFound):  # already gone on billing's side
        await meter.release(hold_id)
    async with factory() as db:
        await db.execute(
            update(HoldRef)
            .where(
                HoldRef.hold_id == hold_id,
                HoldRef.tenant_id == tenant,
                HoldRef.state == REF_RELEASING,
            )
            .values(state=REF_RELEASED)
            .execution_options(**_SYNC)
        )
        await finalize_session(db)
    return True
