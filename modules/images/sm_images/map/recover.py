"""``images.reconcile``'s map pass: what a lost message, a dead worker or a
changed registry left behind, for one tenant.

* A map that is due (:func:`~sm_images.map.schedule.due_row`) and whose claim
  is free or expired is requested again.
* An archive stamped with a redaction gate that is no longer the collection's
  (``redaction.gate_key``: a mutator plugin installed, removed or bumped since
  it was built) is withdrawn - serving already refuses it - and rebuilt.
"""

from __future__ import annotations

from datetime import datetime

from simple_module_db import finalize_session
from sqlalchemy import or_, select

from sm_images.core.access import redaction
from sm_images.map import pmtiles_build
from sm_images.map.revoke import withdraw
from sm_images.map.schedule import MAP_STATE, due_row, request
from sm_images.models import Collection
from sm_images.pipeline.runtime import Runtime

__all__ = ["reconcile_maps"]


async def reconcile_maps(runtime: Runtime, tenant: str, at: datetime) -> int:
    """Request (or withdraw and request) every unclaimed map of ``tenant`` that
    needs it; the caller has bound the tenant. Skipped while tippecanoe cannot
    be found: nothing could build. Returns how many were requested."""
    settings = runtime.settings()
    if pmtiles_build.locate(settings.tippecanoe_path) is None:
        return 0
    claimed = Collection.map_claimed_until
    stmt = select(Collection).where(
        Collection.tenant_id == tenant, or_(claimed.is_(None), claimed < at)
    )
    rows = []
    async with runtime.session_factory() as db:
        for c in (await db.execute(stmt)).scalars():
            stale = c.map_key is not None and c.map_policy_rev != redaction.gate_key(c)
            rows.append((c.id, stale, tuple(getattr(c, col.key) for col in MAP_STATE)))
        await finalize_session(db)
    requested = 0
    for collection_id, stale, state in rows:
        if not stale and not due_row(state, settings):
            continue
        async with runtime.session_factory() as db:
            if stale:
                await withdraw(db, collection_id, runtime=runtime, tenant=tenant)
                requested += 1
            elif await request(db, runtime, tenant, collection_id, at=at) is not None:
                requested += 1
            await finalize_session(db)
    return requested
