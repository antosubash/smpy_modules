"""When a ``release`` op may run: the dependency rules of the outbox.

A release of an image's *old* hold waits until the op named by its
``after_id`` is done and billing confirms the hold the image names now is
committed (:func:`safe_to_release`), so the image is never counted by nothing
while its new hold is merely pending.

**A release never waits on quota.** A commit of a ``held`` hold needs no new
room, so waiting for one always ends. A ``rehold`` does need room, and the
old hold may be what fills it: once a rehold the release waits on (its
``after_id``, or the op settling the image's lapsed current hold) has been
refused for quota (:data:`QUOTA_REFUSED`), the release stops waiting. The
image is under-counted until the rehold fits, rather than both waiting on
each other forever. Releases of holds that were never installed name no
image and never wait at all.
"""

from __future__ import annotations

from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import and_, select

from sm_images.errors import StorageQuotaExceeded
from sm_images.models import BillingOp, Image
from sm_images.models.billing_op import OP_REHOLD

__all__ = ["QUOTA_REFUSED", "blocked", "safe_to_release"]

QUOTA_REFUSED = f"{StorageQuotaExceeded.__name__}%"
"""``last_error`` of a rehold whose reserve billing refused for quota."""


def blocked(op: Any) -> Any:
    """``op`` is a rehold billing refused for quota: nothing may wait on it."""
    return and_(op.done_at.is_(None), op.op == OP_REHOLD, op.last_error.like(QUOTA_REFUSED))


async def safe_to_release(factory: Any, tenant: str, op: Any, meter: Any) -> bool:
    """The image is gone, names no hold, names this very hold, or names a hold
    billing confirms committed - or one that lapsed and whose rehold billing
    refused for quota (waiting would need the room this release frees)."""
    if op.image_id is None:
        return True
    async with factory() as db:
        current = (
            await db.execute(
                select(Image.storage_hold_id)
                .where(Image.id == op.image_id, Image.tenant_id == tenant)
                .execution_options(include_deleted=True)
            )
        ).first()
        await finalize_session(db)
    if current is None or current[0] is None or current[0] == op.hold_id:
        return True
    hold = await meter.get_hold(tenant, current[0])
    if hold is not None and hold.status in ("committed", "held"):
        return hold.status == "committed"  # a held hold's commit needs no room
    return await _quota_blocked(factory, tenant, op.image_id, current[0])


async def _quota_blocked(factory: Any, tenant: str, image_id: Any, hold_id: str) -> bool:
    async with factory() as db:
        found = (
            await db.execute(
                select(BillingOp.id).where(
                    BillingOp.tenant_id == tenant,
                    BillingOp.image_id == image_id,
                    BillingOp.hold_id == hold_id,
                    blocked(BillingOp),
                )
            )
        ).first()
        await finalize_session(db)
    return found is not None
