"""A newsletter subscriber's status change, as a compare-and-set (#101).

A status change is decided from the row — its ``sm_status``, its ``sm_nonce``
— and is only right for the row it was decided from. A confirm that read
``pending`` must not land on a record an unsubscribe has meanwhile rotated
and cleared, and two confirms must not both announce one confirmation. So
:func:`transition` never retries a change it decided earlier:

* every attempt **reloads** the row and asks ``derive`` again, which
  re-checks the nonce and the source status and either answers the change
  (system values, and ordinary values to replace, or ``None`` to keep them),
  answers ``None`` (nothing to do), or raises (the link is no longer good);
* the write is ``update_record`` against **the version that row had** — the
  conditional ``UPDATE … WHERE version = :seen`` is the compare-and-set — and
  a lost race is just the next attempt;
* a record that no longer satisfies its schema takes the same change through
  the guarded merge of :mod:`.system`, pinned to the same version, ordinary
  values included.

Everything happens inside ``events.muted``: the caller announces the change
as a :class:`~sm_records.contracts.events.SubscriptionChanged`, once, and only
when :func:`transition` says it wrote.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import events
from sm_records.models import Record, RecordType
from sm_records.public_submissions.system import _merge_marks, _ordinary, _reload
from sm_records.services import records as record_service
from sm_records.services._payload import field_defs
from sm_records.services.errors import Conflict, ValidationFailed
from sm_records.settings import RecordsSettings

__all__ = ["ATTEMPTS", "Change", "Outcome", "transition"]

logger = logging.getLogger(__name__)

ATTEMPTS: Final = 3

Change = tuple[dict[str, Any], dict[str, Any] | None]
"""``(system values, ordinary values or None to keep them)``."""


@dataclass(frozen=True)
class Outcome:
    record: Record
    before: dict[str, Any]
    """The payload the change was decided from."""
    wrote: bool


def _clearable(
    rtype: RecordType, stored: dict[str, Any], data: dict[str, Any] | None
) -> tuple[dict[str, Any], list[str]]:
    """The ordinary values the direct merge may write: only those that change,
    of ordinary fields that are not ``unique`` (whose claim only the ordinary
    write checks). The rest are named, so the status still lands — an
    unsubscribe must never be refused because a value could not be cleared."""
    if not data:
        return {}, []
    defs = {entry.key: entry for entry in field_defs(rtype)}
    changed = {key: value for key, value in data.items() if stored.get(key) != value}
    kept = sorted(key for key in changed if key not in defs or defs[key].system or defs[key].unique)
    return {key: value for key, value in changed.items() if key not in kept}, kept


async def transition(
    db: AsyncSession,
    rtype: RecordType,
    record: Record,
    derive: Callable[[Record], Change | None],
    *,
    settings: RecordsSettings,
) -> Outcome:
    """Apply ``derive(row)`` to ``record`` as a compare-and-set, re-deciding it
    from the reloaded row on every attempt. ``Conflict`` if the row never
    held still."""
    for _ in range(ATTEMPTS):
        record = await _reload(db, record)
        before = dict(record.data or {})
        change = derive(record)
        if change is None:
            return Outcome(record, before, wrote=False)
        values, data = change
        seen = record.version
        try:
            with events.muted(db):
                written = await record_service.update_record(
                    db,
                    rtype,
                    record,
                    expected_version=seen,
                    data=_ordinary(rtype, record) if data is None else data,
                    settings=settings,
                    system=values,
                )
            return Outcome(written, before, wrote=True)
        except Conflict:
            continue  # the row moved: decide again from what it is now
        except ValidationFailed as exc:
            refused = exc.detail
        clearable, kept = _clearable(rtype, before, data)
        if await _merge_marks(db, rtype, record, values, ordinary=clearable, version=seen):
            logger.warning(
                "records: %s record %s no longer matches its schema (%s); %s written directly%s",
                rtype.key,
                record.uuid,
                refused,
                ", ".join([*values, *clearable]),
                f"; not cleared: {', '.join(kept)}" if kept else "",
            )
            return Outcome(await _reload(db, record), before, wrote=True)
    raise Conflict(f"{rtype.key} record {record.uuid} kept changing; try again")
