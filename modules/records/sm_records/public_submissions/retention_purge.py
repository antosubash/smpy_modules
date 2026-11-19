"""What a retention sweep deletes, and how (#101): the candidates a type may have due, and the
purge of one record under the lock.

Split out of :mod:`sm_records.public_submissions.retention` for the file cap (a moves-only change);
the sweep itself (the lease, the tenants, the batches) stays there.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from sm_records.contracts.public_submissions import (
    KIND_FORM,
    KIND_REGISTRATION,
    KIND_SUBSCRIPTION,
)
from sm_records.core.tenancy import bound_tenant
from sm_records.models import RecordType, tables_for
from sm_records.public_submissions.retention_rules import PENDING, still_due, window_for
from sm_records.records.index.query import Filter, FilterOp, filtered
from sm_records.records.services._lock import lock_type
from sm_records.records.services.records import hard_delete_record, soft_delete_record

__all__ = ["_due", "_purge_one"]


def _due(rtype: RecordType, now: datetime, limit: int, skip: set[str]) -> Any:
    """The uuids that *may* be due, trash included, or ``None`` when the type
    keeps everything. A superset for a list — a pending window starts no
    earlier than the record — that :func:`.retention_rules.still_due` narrows under the lock."""
    config = rtype.public_submissions or {}
    cls = tables_for(rtype).record
    window = window_for(config)
    if (
        config.get("kind") not in (KIND_FORM, KIND_SUBSCRIPTION, KIND_REGISTRATION)
        or window is None
    ):
        return None
    stmt = select(cls.uuid).where(
        cls.type_id == rtype.id,
        cls.tenant_id == bound_tenant(),
        cls.created_at < now - window,
    )
    if config.get("kind") == KIND_SUBSCRIPTION:
        pending = [Filter("sm_status", FilterOp.EQ, PENDING)]
        stmt = filtered(stmt, rtype, list(rtype.fields or []), pending)
    if skip:
        stmt = stmt.where(cls.uuid.not_in(sorted(skip)))
    return stmt.order_by(cls.id).limit(limit).execution_options(include_deleted=True)


async def _purge_one(session: Any, rtype: RecordType, uuid: str, run: Any) -> bool:
    """Delete ``uuid`` if it is still due under the lock; ``False`` when it
    is not (or has gone)."""
    await lock_type(session, rtype)
    cls = tables_for(rtype).record
    stmt = (
        select(cls)
        .where(cls.uuid == uuid, cls.type_id == rtype.id, cls.tenant_id == bound_tenant())
        .with_for_update()
        .execution_options(include_deleted=True, populate_existing=True)
    )
    record = (await session.execute(stmt)).scalars().first()
    if record is None or not still_due(rtype, record, run.now):
        return False
    if not record.is_deleted:
        await soft_delete_record(session, rtype, record, settings=run.settings)
    await hard_delete_record(session, rtype, record)
    return True
