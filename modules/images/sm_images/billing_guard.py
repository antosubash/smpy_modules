"""Room freed for a rehold goes to the rehold first: the under-count guard.

Once the rehold of an image's lapsed hold is refused for quota, the image's
old hold stops waiting for it and is released (:mod:`sm_images.billing_waits`),
so the two never wait on each other. Until the rehold fits, the gauge does not
count the image at all. If a new upload, import item or publication took that
freed room, the rehold would be refused for good and the tenant would store
the image for free.

So every quota pre-check counts the gauge **plus** the bytes of under-counted
images (:func:`under_counted_bytes`): a new reservation fits only if
``gauge + under-counted + new <= limit``. A rehold itself skips the term (it is
what restores the count; counting the other under-counted images against it
could leave two that fit one at a time refused forever).

The worker's meter has no gauge-aware ``check``, so :func:`guard` asks billing
with a probe: a short reservation of ``new + under-counted`` under a key of its
own, released at once. A tenant with nothing under-counted pays no extra call.
The guard is application-level: like any pre-check it can race another
reservation between the probe and the real one.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import func, select

from sm_images.models import BillingOp, Image
from sm_images.models.billing_op import OP_REHOLD

__all__ = ["PROBE_TTL", "guard", "under_counted_bytes"]

logger = logging.getLogger(__name__)

PROBE_TTL = 60
"""Seconds a probe outlives a crash between its reserve and its release."""


async def under_counted_bytes(factory: Any, tenant: str, *, exclude: Any = None) -> int:
    """The bytes of ``tenant``'s images the gauge counts by no hold: each names
    a hold whose rehold is pending with no replacement reserved (a reserved
    replacement is counted by the gauge already). ``exclude`` - an image whose
    own publication is asking (its new hold replaces the lapsed one).

    Driven by the tenant's pending ops (``ix_images_billing_op_due``), joined
    to the image by primary key."""
    pending = select(BillingOp.image_id).where(
        BillingOp.tenant_id == tenant,
        BillingOp.done_at.is_(None),
        BillingOp.op == OP_REHOLD,
        BillingOp.replacement_hold_id.is_(None),
        BillingOp.hold_id == Image.storage_hold_id,
    ).correlate(Image)
    stmt = select(func.coalesce(func.sum(Image.storage_bytes), 0)).where(
        Image.tenant_id == tenant, Image.id.in_(pending)
    )
    if exclude is not None:
        stmt = stmt.where(Image.id != exclude)
    async with factory() as db:
        total = (await db.execute(stmt.execution_options(include_deleted=True))).scalar_one()
        await finalize_session(db)
    return int(total or 0)


async def guard(
    meter: Any, factory: Any, tenant: str, meter_key: str, qty: int, *, exclude: Any = None
) -> bool:
    """Whether ``qty`` more bytes fit once under-counted images are counted.
    No under-count: ``True`` without asking billing (the reserve decides)."""
    under = await under_counted_bytes(factory, tenant, exclude=exclude)
    if under < 1:
        return True
    key = f"images:guard:{uuid.uuid4().hex}"
    probe = await meter.reserve(
        tenant, meter_key, int(qty) + under, key, source="images:guard", ttl=PROBE_TTL
    )
    if not probe.ok:
        return False
    try:
        await meter.release(probe.id)
    except Exception:  # it lapses at PROBE_TTL
        logger.warning("images.billing_guard.release_failed hold=%s", probe.id, exc_info=True)
    return True
