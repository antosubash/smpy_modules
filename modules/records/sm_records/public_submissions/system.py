"""Writing a submission's ``sm_*`` values after it was created (#101).

A delivery mark (``sm_notified_at``) or a spam verdict (``sm_spam``) is an
ordinary ``update_record`` — validated, versioned, one revision — with the
record's own ordinary values sent back unchanged and the new system values
passed through the internal ``system=`` argument, the one way they are
written. It runs inside :func:`sm_records.events.muted`: a mark is
bookkeeping, not a content edit, and announcing it as a ``RecordUpdated``
would tell every subscriber the visitor's message changed.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.index.providers import TypeIndex
from sm_records.index.reduce import snapshot
from sm_records.index.writer import write_index
from sm_records.models import Record, RecordType
from sm_records.schema.compile import to_jsonable
from sm_records.services import records as record_service
from sm_records.services._common import mark_written, type_id_map
from sm_records.services._payload import field_defs
from sm_records.services.errors import Conflict, ValidationFailed
from sm_records.settings import RecordsSettings

__all__ = ["system_update", "try_system_update"]

logger = logging.getLogger(__name__)


def _ordinary(rtype: RecordType, record: Record) -> dict[str, Any]:
    """The record's ordinary values, as an admin save would echo them: only
    keys the schema declares — an undeclared one is the orphan migration's
    to file, and validation would refuse it."""
    declared = {entry.key for entry in field_defs(rtype) if not entry.system}
    return {key: value for key, value in (record.data or {}).items() if key in declared}


async def system_update(
    db: AsyncSession,
    rtype: RecordType,
    record: Record,
    values: dict[str, Any],
    *,
    settings: RecordsSettings,
    data: dict[str, Any] | None = None,
) -> Record:
    """Write ``values`` (system keys only) onto ``record``.

    ``data`` replaces the ordinary values when given (an unsubscribe clears
    them); otherwise they are sent back unchanged.

    Against the version this session holds; a concurrent admin edit that won
    the race is reloaded and the write tried once more, since a mark has
    nothing to merge.
    """
    for attempt in (1, 2):
        try:
            with events.muted(db):
                return await record_service.update_record(
                    db,
                    rtype,
                    record,
                    expected_version=record.version,
                    data=_ordinary(rtype, record) if data is None else data,
                    settings=settings,
                    system=values,
                )
        except Conflict as conflict:
            if attempt == 2:
                raise
            try:
                await db.refresh(record)
            except InvalidRequestError:
                # Gone from under us — trashed or purged by a concurrent
                # request (the soft-delete filter hides it from a refresh):
                # a 409, not a 500. Without ``current``: the row it carries
                # is the one that could not be reloaded, and rendering it
                # into the body would fail the same way.
                raise Conflict(conflict.detail) from None
    raise AssertionError("unreachable")  # pragma: no cover


MARK_ATTEMPTS = 3
"""How often a mark is retried when the row changed under it."""


async def try_system_update(
    db: AsyncSession,
    rtype: RecordType,
    record: Record,
    values: dict[str, Any],
    *,
    settings: RecordsSettings,
    data: dict[str, Any] | None = None,
) -> Record:
    """:func:`system_update`, for a mark that must not block what it marks.

    A record that no longer satisfies its type's schema (a forced restrictive
    change) cannot take an ordinary write until an admin edits it. The spam
    verdict, the not-spam clearing and the delivery mark are bookkeeping about
    server-owned fields, so for such a record they are merged **directly**
    into the stored payload (:func:`_merge_marks`) — otherwise a stale
    ``sm_spam`` would offer *Not spam* again after an ordinary delete, and
    every cycle would mail everyone.

    Each attempt starts from the row as it is now, never from what this
    session loaded earlier: an admin may have repaired the record meanwhile,
    in which case the ordinary write now succeeds, and the direct merge only
    ever adds the mark keys to the current payload under a version check. A
    lost race is retried, up to :data:`MARK_ATTEMPTS` times.
    """
    for attempt in range(MARK_ATTEMPTS):
        if attempt:
            record = await _reload(db, record)
        try:
            return await system_update(db, rtype, record, values, settings=settings, data=data)
        except ValidationFailed as exc:
            refused = exc.detail
        if await _merge_marks(db, rtype, record, values):
            logger.warning(
                "records: %s record %s no longer matches its schema (%s); %s written directly",
                rtype.key,
                record.uuid,
                refused,
                ", ".join(values),
            )
            return await _reload(db, record)
    logger.warning(
        "records: %s record %s: %s NOT written (the row kept changing)",
        rtype.key,
        record.uuid,
        ", ".join(values),
    )
    return record


async def _reload(db: AsyncSession, record: Record) -> Record:
    """The row as stored now, into the same instance (trashed ones included)."""
    cls = type(record)
    stmt = (
        select(cls)
        .where(cls.id == record.id, cls.tenant_id == record.tenant_id)
        .execution_options(include_deleted=True, populate_existing=True)
    )
    return (await db.execute(stmt)).scalars().one()


async def _merge_marks(
    db: AsyncSession,
    rtype: RecordType,
    record: Record,
    values: dict[str, Any],
    *,
    ordinary: dict[str, Any] | None = None,
    version: int | None = None,
) -> bool:
    """Compare-and-set the mark keys into the stored payload.

    Reads the current payload and version, adds *only* ``values`` (system
    fields — a unique one is refused, since its claim is checked by the
    ordinary write alone) and ``ordinary`` (declared ordinary fields an
    unsubscribe clears, in the same step), and writes it back ``WHERE version
    = <read>`` in this tenant. ``version`` pins the read too: a caller that
    decided the change from the row at that version gets ``False`` if the row
    has moved since. An indexed key (a subscriber's ``sm_status``) has its
    index rows rebuilt from the merged payload, so a filter sees the new value.
    No validation and no revision: nothing but server-owned bookkeeping
    changes.
    """
    defs = {entry.key: entry for entry in field_defs(rtype)}
    ordinary = ordinary or {}
    if any(key not in defs or not defs[key].system or defs[key].unique for key in values):
        return False
    if any(key not in defs or defs[key].system or defs[key].unique for key in ordinary):
        return False
    cls = type(record)
    where = (cls.id == record.id, cls.tenant_id == record.tenant_id)
    read = select(cls.data, cls.version).where(*where)
    if version is not None:
        read = read.where(cls.version == version)
    current = (await db.execute(read.execution_options(include_deleted=True))).first()
    if current is None:
        return False
    merged = {**(current.data or {}), **to_jsonable(ordinary), **to_jsonable(values)}
    stmt = (
        update(cls)
        .where(*where, cls.version == current.version)
        .values(data=merged, version=current.version + 1)
        .execution_options(synchronize_session=False, include_deleted=True)
    )
    result = await db.execute(stmt)
    mark_written(db)
    if result.rowcount != 1:
        return False
    if any(defs[key].indexed for key in (*values, *ordinary)):
        before = snapshot(record, current.data or {})
        record = await _reload(db, record)
        resolver = TypeIndex(await type_id_map(db))
        await write_index(db, record, rtype, resolve_type_id=resolver, previous=before)
    return True
