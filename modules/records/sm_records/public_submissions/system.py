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

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.models import Record, RecordType
from sm_records.services import records as record_service
from sm_records.services._payload import field_defs
from sm_records.services.errors import Conflict
from sm_records.settings import RecordsSettings

__all__ = ["system_update"]


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
        except Conflict:
            if attempt == 2:
                raise
            await db.refresh(record)
    raise AssertionError("unreachable")  # pragma: no cover
