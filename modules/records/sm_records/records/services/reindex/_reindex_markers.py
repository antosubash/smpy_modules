"""records services _reindex_markers helpers."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.core.tenancy._cross_tenant import read_all
from sm_records.models import RecordType
from sm_records.records.index.reindex import clear_pending, pending_map
from sm_records.records.services._common import reload
from sm_records.records.services.claims._claims import lock_type
from sm_records.records.services.errors import Conflict

logger = logging.getLogger("sm_records.records.services.reindex_runner")


async def pending_type_ids(db: AsyncSession) -> list[int]:
    """Every type, **in every tenant**, with at least one ``reindex_pending`` entry.

    Filtered in Python: the column is plain ``JSON``, so "is this object empty"
    is spelled differently on every backend, and there are tens of types rather
    than millions. Read across tenants (:func:`read_all`) because the ids go
    to :func:`run_pending`, which binds each type's own tenant.
    """
    stmt = select(RecordType.id, RecordType.reindex_pending).order_by(RecordType.id)
    rows = (await read_all(db, stmt)).all()
    return [int(type_id) for type_id, pending in rows if pending and type_id is not None]


async def _clear_rebuilt(
    session: AsyncSession, rtype: RecordType, keys: list[str], started_at_schema: int
) -> None:
    """Clear the markers this run actually rebuilt — see :func:`run_pending`.

    Called holding the type lock (:func:`_rebuild`); taken again so it never
    runs without: the read-modify-write of one JSON column is what races."""
    try:
        await lock_type(session, rtype)
    except Conflict:
        # The lock refuses a type deleted while the rebuild ran; that is not an
        # error here (below), whereas a move or a busy lock still is.
        if await reload(session, RecordType, rtype.id) is None:
            return
        raise
    fresh = await reload(session, RecordType, rtype.id)
    if fresh is None:  # the type was deleted while the rebuild ran; its markers went with it
        return
    if fresh.schema_version != started_at_schema:
        logger.info(
            "records: type %s changed schema during its rebuild; leaving %d marker(s) pending",
            rtype.id,
            len(pending_map(fresh)),
        )
        return
    await clear_pending(session, fresh, keys)
