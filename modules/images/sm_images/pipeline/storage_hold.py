"""The storage gauge at the executor's fenced publication (plan decision 10).

A step that publishes objects (a display copy, a rendition set) changes what
the image stores, so ``Image.storage_bytes`` and its hold move with it:

1. **Before the completion** (:func:`reserve`): the new total - the original,
   the display copy and the renditions, with this attempt's objects in place
   of the ones they replace - is reserved as a ``held`` hold, keyed by the
   attempt's nonce. Not inside the completion transaction: billing writes in
   its own transaction, which on file-backed SQLite would wait on the image
   lock the completion holds (the object intents' rule, ``finish.stage``). A
   refusal is ``StorageQuotaExceeded``: the caller deletes the staged objects
   and fails the step ``quota_exceeded``; nothing is published.

   **The reservation's TTL** is the step lease plus :data:`SLACK` (at least
   billing's default). A completion is accepted only within its lease, and the
   reservation is taken after the step ran, so it outlives every completion
   that can still succeed; the slack covers the outbox's commit right after.
   :func:`renew` extends it anyway when it is within :data:`MARGIN` of lapsing
   before the image lock is taken.
2. **In the completion, under the image lock and after the fenced writes**
   (:func:`record`): a reservation past its deadline is refused, and so is one
   for another total than the rows now add up to (another publication moved it
   in between) - both are treated like a lost fence: rolled back, planned
   again. Otherwise ``storage_bytes`` and ``storage_hold_id`` are written, and
   the settlement - ``commit`` the new hold, then ``release`` the old one - goes
   to the outbox in the same transaction (:mod:`sm_images.billing_ops`).
3. **A completion that keeps nothing** releases the new hold through the
   outbox (:func:`unhold`).

Without billing the hold is ``None`` and only ``storage_bytes`` is written.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update

from sm_images import billing, billing_ops, hold_refs
from sm_images.models import Image, Rendition
from sm_images.pipeline.runtime import Runtime

__all__ = ["MARGIN", "SLACK", "Planned", "parts", "record", "renew", "reserve", "unhold"]

logger = logging.getLogger(__name__)
SLACK = 300
MIN_TTL = 900
MARGIN = timedelta(seconds=60)


@dataclass(frozen=True)
class Planned:
    total: int
    hold: str | None
    expires_at: datetime | None = None


async def parts(
    db: Any, tenant: str, image_id: uuid.UUID, *, include_deleted: bool = False
) -> tuple[int, int, int, str | None] | None:
    """``(original, display copy, renditions, hold)`` of the image's stored
    bytes; ``None`` when there is no such image."""
    stmt = select(Image.size_bytes, Image.display_bytes, Image.storage_hold_id).where(
        Image.id == image_id, Image.tenant_id == tenant
    )
    image = (await db.execute(stmt.execution_options(include_deleted=include_deleted))).first()
    if image is None:
        return None
    rendered = await db.execute(
        select(func.coalesce(func.sum(Rendition.size_bytes), 0)).where(
            Rendition.image_id == image_id, Rendition.tenant_id == tenant
        )
    )
    return int(image[0]), int(image[1]), int(rendered.scalar_one()), image[2]


def ttl_for(runtime: Runtime) -> int:
    return max(int(runtime.settings().step_lease_seconds) + SLACK, MIN_TTL)


async def reserve(runtime: Runtime, loaded: Any, staged: Any) -> Planned | None:
    """Reserve the total the image will store once ``staged`` is published;
    ``None`` when the step stages no object."""
    if not staged.keys:
        return None
    async with runtime.session_factory() as db:
        found = await parts(db, loaded.tenant, loaded.image_id)
    if found is None:
        raise LookupError("the image is gone")
    original, display, renditions, _ = found
    if staged.display_key is not None:
        display = staged.display_bytes
    if staged.renditions:
        renditions = sum(r[3] for r in staged.renditions.values())
    planned = original + display + renditions
    key = billing.hold_key(loaded.image_id, staged.attempt)
    hold = await billing.reserve(
        runtime.session_factory, loaded.tenant, planned, key, ttl=ttl_for(runtime)
    )
    if hold is None:
        return Planned(planned, None)
    return Planned(planned, hold.id, hold.expires_at)


async def renew(runtime: Runtime, planned: Planned | None) -> Planned | None:
    """Extend a reservation close to lapsing, before the image lock is taken.
    A failure is left to :func:`record`, which then refuses it."""
    if planned is None or planned.hold is None or planned.expires_at is None:
        return planned
    if planned.expires_at - datetime.now(UTC) > MARGIN:
        return planned
    try:
        hold = await billing.extend(runtime.session_factory, planned.hold, ttl_for(runtime))
    except Exception:
        logger.warning("images.storage_hold.renew_failed hold=%s", planned.hold, exc_info=True)
        return planned
    return planned if hold is None else replace(planned, expires_at=hold.expires_at)


async def record(
    db: Any, runtime: Runtime, loaded: Any, planned: Planned | None, now: datetime
) -> bool:
    """Write the image's new total (under the lock, after the publication) and
    its settlement; ``False`` when the reservation lapsed or was for another
    total - the caller must roll back."""
    if planned is None:
        return True
    if planned.hold is not None and planned.expires_at is not None and now >= planned.expires_at:
        return False
    found = await parts(db, loaded.tenant, loaded.image_id)
    assert found is not None  # the caller holds its lock
    original, display, renditions, old = found
    total = original + display + renditions
    if planned.hold is not None and total != planned.total:
        return False
    values: dict[str, Any] = {"storage_bytes": total}
    if planned.hold is not None:
        values["storage_hold_id"] = planned.hold
        await billing_ops.add_swap(
            db, loaded.image_id, planned.hold, total, old, factory=runtime.session_factory
        )
        await hold_refs.installed(db, planned.hold, loaded.image_id)
        if old != planned.hold:
            await hold_refs.orphan(db, loaded.tenant, old)
    await db.execute(
        update(Image)
        .where(Image.id == loaded.image_id, Image.tenant_id == loaded.tenant)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    return True


async def unhold(runtime: Runtime, loaded: Any, planned: Planned | None) -> None:
    """Nothing was published: give the reserved capacity back (outbox). The
    hold was never installed, so its release names no image and waits on
    nothing (the image's current hold may need the very quota it holds)."""
    if planned is not None and planned.hold is not None:
        await billing_ops.release_now(runtime.session_factory, None, planned.hold)
