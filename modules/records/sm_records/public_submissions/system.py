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

from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.models import Record, RecordType
from sm_records.schema.compile import to_jsonable
from sm_records.services import records as record_service
from sm_records.services._common import mark_written
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
) -> Record:
    """Write ``values`` (system keys only) onto ``record``.

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
                    data=_ordinary(rtype, record),
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


async def try_system_update(
    db: AsyncSession,
    rtype: RecordType,
    record: Record,
    values: dict[str, Any],
    *,
    settings: RecordsSettings,
) -> Record:
    """:func:`system_update`, for a mark that must not block what it marks.

    A record that no longer satisfies its type's schema (a forced restrictive
    change) cannot take an ordinary write until an admin edits it. The spam
    verdict, the not-spam clearing and the delivery mark are bookkeeping about
    server-owned fields, so for such a record they are written **directly**
    onto the stored payload (:func:`_write_marks`), leaving the visitor's
    values exactly as they are — otherwise a stale ``sm_spam`` would offer
    *Not spam* again after an ordinary delete, and every cycle would mail
    everyone. Nothing was written when validation refused.
    """
    try:
        return await system_update(db, rtype, record, values, settings=settings)
    except ValidationFailed as exc:
        written = await _write_marks(db, rtype, record, values)
        logger.warning(
            "records: %s record %s no longer matches its schema (%s); %s %s directly",
            rtype.key,
            record.uuid,
            exc.detail,
            ", ".join(values),
            "written" if written else "NOT written",
        )
        return record


async def _write_marks(
    db: AsyncSession, rtype: RecordType, record: Record, values: dict[str, Any]
) -> bool:
    """Set system values on the stored payload, no validation, no revision.

    Only for system fields that are not indexed (every contact-form one): an
    indexed key would leave its index row behind, so it is refused. The
    version moves, so an editor holding the record sees the change on save.
    """
    system = {entry.key: entry for entry in field_defs(rtype) if entry.system}
    if any(key not in system or system[key].indexed for key in values):
        return False
    record.data = {**(record.data or {}), **to_jsonable(values)}
    record.version = record.version + 1
    db.add(record)
    await db.flush()
    mark_written(db)
    return True
