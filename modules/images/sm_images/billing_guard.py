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

**An image is under-counted unless billing confirms its hold.** Only images
whose current hold still has a pending ``commit`` or ``rehold`` op are in
doubt (a done op means billing committed the hold, and a committed hold never
lapses). Each of those counts as covered only while its hold ref is
``installed`` and billing reports the hold live: a ``commit``'s hold
``committed`` or ``held`` and unexpired, a ``rehold``'s recorded replacement
likewise. An expired, released or unknown hold, or a rehold with no
replacement, is under-counted. At most :data:`CONFIRM_CAP` holds are asked
about per call; the rest count as under-counted (fail closed).

The worker's meter has no gauge-aware ``check``, so :func:`guard` asks billing
with a probe: a short reservation of ``new + under-counted`` under a key of its
own, released at once. A tenant with nothing under-counted pays no extra call.

**Atomic per tenant** (:func:`serialized`): the guard and the reservation after
it run under one lease, ``images:quota:{tenant}``, so no two reservations of a
tenant can both pass the probe before either reserves. It is held across the
two billing calls only - never across the caller's transaction (on SQLite the
lease and billing each take the writer lock briefly). It is taken only when
the tenant's plan sets a limit; :class:`QuotaBusy` when it is not had within
:data:`LEASE_WAIT`.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from simple_module_core.leases import lease
from simple_module_db import finalize_session
from sqlalchemy import and_, func, select

from sm_images.errors import QuotaBusy
from sm_images.models import BillingOp, HoldRef, Image
from sm_images.models.billing_op import OP_COMMIT, OP_REHOLD
from sm_images.models.hold_ref import REF_INSTALLED

__all__ = [
    "CONFIRM_CAP",
    "LEASE_TTL",
    "LEASE_WAIT",
    "PROBE_TTL",
    "guard",
    "serialized",
    "under_counted_bytes",
]

logger = logging.getLogger(__name__)

PROBE_TTL = 60
"""Seconds a probe outlives a crash between its reserve and its release."""
LEASE_TTL = 30.0
"""Seconds the quota lease outlives a crash while it is held."""
LEASE_WAIT = 10.0
"""Seconds a reservation waits for the tenant's quota lease."""
CONFIRM_CAP = 50
"""Holds one guard call asks billing about."""
BUSY = "Storage is being allocated for other uploads; try again in a moment"
_LIVE = ("held", "committed")


def _in_doubt(tenant: str, exclude: Any) -> Any:
    """Images whose current hold has a pending ``commit`` or ``rehold``."""
    stmt = (
        select(
            Image.id,
            Image.storage_bytes,
            Image.storage_hold_id,
            BillingOp.op,
            BillingOp.replacement_hold_id,
            HoldRef.state,
        )
        .join(
            BillingOp,
            and_(
                BillingOp.tenant_id == tenant,
                BillingOp.done_at.is_(None),
                BillingOp.op.in_((OP_COMMIT, OP_REHOLD)),
                BillingOp.image_id == Image.id,
                BillingOp.hold_id == Image.storage_hold_id,
            ),
        )
        .outerjoin(
            HoldRef, and_(HoldRef.tenant_id == tenant, HoldRef.hold_id == Image.storage_hold_id)
        )
        .where(Image.tenant_id == tenant)
        .order_by(BillingOp.id)
    )
    return stmt if exclude is None else stmt.where(Image.id != exclude)


async def under_counted_bytes(factory: Any, tenant: str, meter: Any, *, exclude: Any = None) -> int:
    """The bytes of ``tenant``'s images the gauge may count by no hold (see
    the module docstring). ``exclude`` - an image whose own publication is
    asking (its new hold replaces the one in doubt)."""
    stmt = _in_doubt(tenant, exclude).execution_options(include_deleted=True)
    async with factory() as db:
        rows = list((await db.execute(stmt.limit(CONFIRM_CAP))).all())
        rest = 0
        if len(rows) == CONFIRM_CAP:  # beyond the cap: under-counted, unasked
            seen = [r[0] for r in rows]
            tail = select(func.coalesce(func.sum(Image.storage_bytes), 0)).where(
                Image.id.in_(_in_doubt(tenant, exclude).with_only_columns(Image.id)),
                Image.id.not_in(seen),
            )
            rest = int(
                (await db.execute(tail.execution_options(include_deleted=True))).scalar_one()
            )
        await finalize_session(db)
    statuses: dict[str, str | None] = {}  # one billing read per hold per call

    async def status(hold_id: str) -> str | None:
        if hold_id not in statuses:
            found = await meter.get_hold(tenant, hold_id)
            statuses[hold_id] = None if found is None else found.status
        return statuses[hold_id]

    total, counted = rest, set()
    for image_id, size, current, op, replacement, ref in rows:
        if image_id in counted:
            continue
        counted.add(image_id)
        covering = current if op == OP_COMMIT else replacement
        if ref != REF_INSTALLED or covering is None or await status(covering) not in _LIVE:
            total += int(size or 0)
    return total


@contextlib.asynccontextmanager
async def serialized(meter: Any, tenant: str, meter_key: str) -> AsyncIterator[None]:
    """Hold the tenant's quota lease for the body - only when its plan limits
    ``meter_key`` (no limit: nothing to protect, no lease)."""
    if (await meter.check(tenant, meter_key, 0)).limit is None:
        yield
        return
    held = lease(f"images:quota:{tenant}", ttl=LEASE_TTL, wait=LEASE_WAIT)
    if not await held.acquire():
        raise QuotaBusy(BUSY)
    try:
        yield
    finally:
        try:
            await held.release()
        except Exception:  # it lapses at LEASE_TTL
            logger.warning("images.billing_guard.lease_release_failed", exc_info=True)


async def guard(
    meter: Any, factory: Any, tenant: str, meter_key: str, qty: int, *, exclude: Any = None
) -> bool:
    """Whether ``qty`` more bytes fit once under-counted images are counted.
    No under-count: ``True`` without asking billing (the reserve decides)."""
    under = await under_counted_bytes(factory, tenant, meter, exclude=exclude)
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
