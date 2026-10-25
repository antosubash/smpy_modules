"""Marking fields mid-rebuild in the schema write's own transaction — split
from :mod:`sm_records.services.schema_change` for the 300-line cap."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import REINDEX_ALL
from sm_records.index.reindex import pending_map
from sm_records.models import RecordType
from sm_records.services._common import utcnow

__all__ = ["mark_pending"]


async def mark_pending(
    db: AsyncSession, rtype: RecordType, keys: list[str], *, whole_type: bool
) -> None:
    """Step 1 of §8.5, in the same transaction as the ``fields`` write. Every
    marked key is refused as a filter or a sort key — a 409 naming it — until
    the rebuild clears it; partial results without comment is the failure
    mode this ceremony is for."""
    if not keys and not whole_type:
        return
    pending = pending_map(rtype)
    now = utcnow().isoformat()
    for key in keys:
        pending[key] = now
    if whole_type:
        pending[REINDEX_ALL] = now
    rtype.reindex_pending = pending
    db.add(rtype)
    await db.flush()
