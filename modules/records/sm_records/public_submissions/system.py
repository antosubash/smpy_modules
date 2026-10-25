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
from sm_records.services import records as record_service
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
                # the original 409, not a 500.
                raise conflict from None
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
    change) cannot take *any* write until an admin edits it, and a system
    write is a write. The spam verdict, the not-spam clearing and the
    delivery mark are bookkeeping: refused here, they are logged and skipped
    — the record is still trashed, restored or mailed, and the outbox does not
    retry a mail it already sent. Nothing was written when validation refused.
    """
    try:
        return await system_update(db, rtype, record, values, settings=settings)
    except ValidationFailed as exc:
        logger.warning(
            "records: %s record %s no longer matches its schema; %s not recorded (%s)",
            rtype.key,
            record.uuid,
            ", ".join(values),
            exc.detail,
        )
        return record
