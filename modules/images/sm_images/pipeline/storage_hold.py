"""The storage gauge at the executor's fenced publication (plan decision 10).

A step that publishes objects (a display copy, a rendition set) changes what
the image stores, so ``Image.storage_bytes`` and its hold move with it - by
billing's atomic swap, which commits the new hold and releases the old one in
one transaction. When it runs depends on the direction:

* **The image grows** (:func:`reserve`, before the completion): a ``swap`` op
  is written, claimed by this attempt, under the image's row lock - only when
  the image has no swap still pending (one is settled inline first; if it
  stays pending, :class:`HoldBusy`). Then billing swaps. A refusal is
  ``StorageQuotaExceeded``: the old hold still counts, the staged objects are
  deleted, the step fails ``quota_exceeded`` and nothing is published.
* **The image shrinks** (or keeps its size): nothing is asked of billing
  before; the completion queues the swap with its writes, and it settles after
  the commit. A shrink always fits.

**In the completion, under the image lock and after the fenced writes**
(:func:`record`): the total the rows now add up to must be the one planned,
and a grown image must still name the hold the swap replaced - else it is
treated like a lost fence (rolled back, planned again). Then
``storage_bytes``, the new hold and the op's completion (conditional on our
claim) commit together. **A completion that keeps nothing** hands its op to
the settler (:func:`abandon`), which installs the swapped hold and queues the
correcting shrink back to what the image stores.

Without billing only ``storage_bytes`` is written.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import func, select, update

from sm_images import billing, billing_ops
from sm_images.billing_settle import CLAIM
from sm_images.errors import StorageQuotaExceeded
from sm_images.models import Image, Rendition
from sm_images.models.billing_op import OP_SWAP
from sm_images.pipeline.claim import lock_image
from sm_images.pipeline.runtime import Runtime

__all__ = ["HoldBusy", "Planned", "abandon", "parts", "record", "reserve"]


class HoldBusy(Exception):  # noqa: N818 - reads as the condition
    """The image's hold has a swap still pending: the step runs again later."""


@dataclass(frozen=True)
class Planned:
    total: int
    hold: str | None = None
    """A grown image's new hold (committed by billing already)."""
    old: str | None = None
    """The hold that swap replaced: what the image must still name."""
    op: billing_ops.Claimed | None = None
    queue: bool = False
    """Shrinking (or same size) with billing: the completion queues the swap."""


async def parts(
    db: Any, tenant: str, image_id: uuid.UUID
) -> tuple[int, int, int, str | None, int] | None:
    """``(original, display copy, renditions, hold, storage_bytes)`` of the
    image's stored bytes; ``None`` when there is no such image."""
    stmt = select(
        Image.size_bytes, Image.display_bytes, Image.storage_hold_id, Image.storage_bytes
    ).where(Image.id == image_id, Image.tenant_id == tenant)
    image = (await db.execute(stmt)).first()
    if image is None:
        return None
    rendered = await db.execute(
        select(func.coalesce(func.sum(Rendition.size_bytes), 0)).where(
            Rendition.image_id == image_id, Rendition.tenant_id == tenant
        )
    )
    return int(image[0]), int(image[1]), int(rendered.scalar_one()), image[2], int(image[3])


async def reserve(runtime: Runtime, loaded: Any, staged: Any) -> Planned | None:
    """Plan the total the image will store once ``staged`` is published, and
    swap its hold first when that grows it; ``None`` when nothing is staged."""
    if not staged.keys:
        return None
    factory = runtime.session_factory
    async with factory() as db:
        found = await parts(db, loaded.tenant, loaded.image_id)
    if found is None:
        raise LookupError("the image is gone")
    original, display, renditions, _, _ = found
    if staged.display_key is not None:
        display = staged.display_bytes
    if staged.renditions:
        renditions = sum(r[3] for r in staged.renditions.values())
    planned = original + display + renditions
    meter = billing.storage_meter(factory)
    if meter is None:
        return Planned(planned)
    opened = await _open(factory, loaded, planned, staged.attempt)
    if opened is None:
        return Planned(planned, queue=True)
    op, old = opened
    try:
        hold = await billing.swap(
            factory, loaded.tenant, old, planned, op.key, meter, not_after=op.not_after
        )
    except StorageQuotaExceeded as exc:  # nothing changed: the old hold still counts
        async with factory() as db:
            await billing_ops.finish(db, op, None, f"{type(exc).__name__}: {exc}")
            await finalize_session(db)
        raise
    except Exception:
        await _hand_back(factory, op)
        raise
    return Planned(planned, hold.id, old, op)


async def _open(
    factory: Any, loaded: Any, planned: int, attempt: str
) -> tuple[billing_ops.Claimed, str | None] | None:
    """Write our claimed ``swap`` op when ``planned`` grows the image; ``None``
    when it does not. Settles a pending swap of the image once first;
    :class:`HoldBusy` when one is still pending."""
    tenant, image_id = loaded.tenant, loaded.image_id
    for first in (True, False):
        async with factory() as db:
            if await lock_image(db, tenant, image_id) is None:
                raise LookupError("the image is gone")
            found = await parts(db, tenant, image_id)
            assert found is not None
            if planned <= found[4]:
                await db.rollback()
                return None
            waiting = await billing_ops.pending_swaps(db, tenant, image_id)
            if not waiting:
                key = billing.hold_key(image_id, attempt)
                op = await billing_ops.open_op(
                    db, OP_SWAP, image_id, planned, key, claim=CLAIM, old=found[3]
                )
                await finalize_session(db)
                return op, found[3]
            await db.rollback()
        if first:
            await billing_ops.settle(factory, tenant, waiting)
    raise HoldBusy(str(image_id))


async def record(db: Any, runtime: Runtime, loaded: Any, planned: Planned | None) -> bool:
    """Write the image's new total (under the lock, after the publication)
    and settle its hold; ``False`` when the total is not the one planned, the
    image names another hold, or our op was taken over - roll back."""
    if planned is None:
        return True
    found = await parts(db, loaded.tenant, loaded.image_id)
    assert found is not None  # the caller holds its lock
    original, display, renditions, hold, stored = found
    total = original + display + renditions
    if total != planned.total:
        return False
    values: dict[str, Any] = {"storage_bytes": total}
    if planned.op is not None:
        if hold != planned.old or not await billing_ops.finish(db, planned.op, planned.hold):
            return False
        values["storage_hold_id"] = planned.hold
    elif planned.queue and total != stored:
        await billing_ops.add_swap(db, loaded.image_id, total, factory=runtime.session_factory)
    await db.execute(
        update(Image)
        .where(Image.id == loaded.image_id, Image.tenant_id == loaded.tenant)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    return True


async def abandon(runtime: Runtime, planned: Planned | None) -> None:
    """Nothing was published: hand a grown image's swap to the settler, which
    installs its hold and shrinks it back to what the image stores."""
    if planned is not None and planned.op is not None:
        await _hand_back(runtime.session_factory, planned.op)


async def _hand_back(factory: Any, op: billing_ops.Claimed) -> None:
    async with factory() as db:
        await billing_ops.hand_back(db, op, factory)
        await finalize_session(db)
