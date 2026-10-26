"""Pruning delivery bookkeeping that nothing can need any more (#101).

``records_submission_delivery`` remembers, per ``(record, attempt,
recipient)``, that a send went through — which is what stops a retry of that
attempt from mailing the recipient twice (:mod:`.delivery`). So a row may
only go once **its whole attempt is finished**; deleting one sent marker of
an attempt that can still be retried (one recipient sent, another failed, the
workers down past the horizon) would make the resumed attempt mail the first
recipient again.

An attempt's rows are deleted, all together, when either

* the record is **gone** — a record that no longer exists is never mailed
  (``delivery.load``), so none of its attempts can resume; or
* every row of the attempt is **sent**, the newest send is older than the
  horizon (``public_submissions_delivery_retention_days``), and the record's
  delivery mark is set (``sm_notified_at``, or ``sm_confirm_sent_at`` for a
  list) — the record has been delivered, so the attempt has nothing left to
  do.

An attempt with a row never sent stays, however old: it is retryable until
the record is purged, and the purge deletes it then.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select, tuple_

from sm_records import events
from sm_records.contracts.public_submissions import KIND_SUBSCRIPTION
from sm_records.models import RecordType, SubmissionDelivery, tables_for
from sm_records.tenancy import bound_tenant

__all__ = ["prune_deliveries"]

_CHUNK = 500


def _mark(rtype: RecordType) -> str:
    kind = (rtype.public_submissions or {}).get("kind")
    return "sm_confirm_sent_at" if kind == KIND_SUBSCRIPTION else "sm_notified_at"


async def _marks(session: Any, types: Sequence[RecordType], uuids: list[str]) -> dict[str, bool]:
    """``{uuid: delivered}`` for the records among ``uuids`` that still exist
    (the trash included); a uuid missing from the answer is gone."""
    tenant = bound_tenant()
    found: dict[str, bool] = {}
    for rtype in types:
        cls = tables_for(rtype).record
        for start in range(0, len(uuids), _CHUNK):
            stmt = select(cls.uuid, cls.data).where(
                cls.tenant_id == tenant,
                cls.type_id == rtype.id,
                cls.uuid.in_(uuids[start : start + _CHUNK]),
            )
            rows = await session.execute(stmt.execution_options(include_deleted=True))
            for uuid, data in rows.all():
                found[str(uuid)] = bool((data or {}).get(_mark(rtype)))
    return found


async def prune_deliveries(
    session_factory: Callable[[], Any], types: Sequence[RecordType], cutoff: datetime
) -> int:
    """Delete the bound tenant's finished attempts (see the module docstring);
    the number of rows deleted."""
    table = SubmissionDelivery
    tenant = bound_tenant()
    session = session_factory()
    try:
        groups = (
            await session.execute(
                select(
                    table.record_uuid,
                    table.attempt,
                    func.count(),
                    func.count(table.sent_at),
                    func.max(table.sent_at),
                )
                .where(table.tenant_id == tenant)
                .group_by(table.record_uuid, table.attempt)
            )
        ).all()
        if not groups:
            await events.rollback(session)
            return 0
        marks = await _marks(session, types, sorted({str(g[0]) for g in groups}))
        done: list[tuple[str, str]] = []
        for uuid, attempt, rows, sent, newest in groups:
            uuid = str(uuid)
            if uuid not in marks:
                done.append((uuid, attempt))  # the record is gone
            elif rows == sent and marks[uuid] and newest is not None:
                stamp = newest if newest.tzinfo else newest.replace(tzinfo=cutoff.tzinfo)
                if stamp < cutoff:
                    done.append((uuid, attempt))
        deleted = 0
        for start in range(0, len(done), _CHUNK):
            keys = done[start : start + _CHUNK]
            result = await session.execute(
                sa_delete(table)
                .where(
                    table.tenant_id == tenant,
                    tuple_(table.record_uuid, table.attempt).in_(keys),
                )
                .execution_options(synchronize_session=False)
            )
            deleted += int(result.rowcount or 0)
        await events.commit(session)
        return deleted
    except BaseException:
        await events.rollback(session)
        raise
    finally:
        await session.close()
