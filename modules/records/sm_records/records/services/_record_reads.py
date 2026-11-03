"""records services _record_reads helpers."""

from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sm_records.core._text import has_nul
from sm_records.models import Record, RecordType, tables_for
from sm_records.records.services.errors import NotFound
from sm_records.core.tenancy import bound_tenant


async def _by_uuid(db: AsyncSession, rtype: RecordType, uuid: str, *, trashed: bool) -> Record:
    """One record of ``rtype`` by uuid, out of whichever table set it lives in
    (Phase 5 §6.3). ``trashed`` lifts the framework's soft-delete filter, which
    is the only way to load a row it hides — restore and purge both need it."""
    # A uuid carrying a NUL is a bound ``varchar`` parameter and therefore the
    # driver's own refusal — a 500 where "no such record" is both true and
    # already expressible. See :mod:`sm_records.core._text`.
    if has_nul(uuid):
        raise NotFound(f"no {rtype.key} record with uuid {uuid!r}")
    cls = tables_for(rtype).record
    # The tenant said explicitly on a natural-key lookup (tenancy design §E):
    # uuids are unique per tenant only, so the loader criteria are not what
    # this one rests on.
    stmt = select(cls).where(
        cls.uuid == uuid, cls.type_id == rtype.id, cls.tenant_id == bound_tenant()
    )
    if trashed:
        stmt = stmt.execution_options(include_deleted=True)
    record = (await db.execute(stmt)).scalars().first()
    if record is None:
        raise NotFound(f"no {rtype.key} record with uuid {uuid!r}")
    return record


async def get_record(db: AsyncSession, rtype: RecordType, uuid: str) -> Record:
    return await _by_uuid(db, rtype, uuid, trashed=False)


async def get_deleted_record(db: AsyncSession, rtype: RecordType, uuid: str) -> Record:
    """The trash view."""
    return await _by_uuid(db, rtype, uuid, trashed=True)
