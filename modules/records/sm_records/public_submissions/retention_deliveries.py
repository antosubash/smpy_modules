"""Pruning delivery bookkeeping that nothing can need any more (#101).

``records_submission_delivery`` remembers, per ``(record, attempt,
recipient)``, that a send went through — which is what stops a retry of that
attempt from mailing the recipient twice (:mod:`.delivery`). So a row may
only go once **its whole attempt is finished**, and "finished" is never
inferred from the rows that happen to exist (a worker can crash before it
claimed the next recipient, leaving every existing row "sent"). An attempt's
rows are deleted, all together, only when

* the attempt is **complete** — it has the completion row
  (:data:`.attempts.COMPLETE`) that ``send_all`` writes once every recipient
  of its full set is sent — and the newest of its rows is older than the
  horizon (``public_submissions_delivery_retention_days``); or
* it is a newsletter **confirmation that can never resume**: the subscriber
  is no longer pending (confirmed or unsubscribed; a confirmation is built
  only for a pending subscriber, and a return to pending starts a new
  attempt), past the horizon likewise; or
* the record is **verifiably gone** — looked up directly, at prune time, by
  tenant and uuid in every record table (the trash included), in one
  statement and so one snapshot: a record moving between collections is seen
  in one table or the other, never in neither. A record that no longer exists
  is never mailed (``delivery.load``), so none of its attempts can resume.

Each batch is committed on its own, and the sweep's ``keep`` (lease renewal)
runs before every commit, so a sweep that lost its lease stops pruning too.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, case, func, select, tuple_, union_all
from sqlalchemy import delete as sa_delete

from sm_records import events
from sm_records.contracts.public_submissions import KIND_SUBSCRIPTION
from sm_records.models import RecordType, SubmissionDelivery, table_sets
from sm_records.public_submissions.attempts import COMPLETE, MARKERS
from sm_records.public_submissions.retention_rules import PENDING
from sm_records.tenancy import bound_tenant

__all__ = ["prune_deliveries"]

_CHUNK = 500


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment


async def _records(session: Any, uuids: list[str]) -> dict[str, tuple[str | None, Any]]:
    """``{uuid: (kind, data)}`` of the records among ``uuids`` that exist now,
    in whichever table they live, the trash included. One statement per
    chunk, so one snapshot."""
    tenant = bound_tenant()
    found: dict[str, tuple[int, Any]] = {}
    for start in range(0, len(uuids), _CHUNK):
        chunk = uuids[start : start + _CHUNK]
        parts = [
            select(ts.record.uuid, ts.record.type_id, ts.record.data).where(
                ts.record.tenant_id == tenant, ts.record.uuid.in_(chunk)
            )
            for ts in table_sets()
        ]
        stmt = union_all(*parts) if len(parts) > 1 else parts[0]
        rows = await session.execute(stmt.execution_options(include_deleted=True))
        for uuid, type_id, data in rows.all():
            found[str(uuid)] = (int(type_id), data)
    kinds: dict[int, str | None] = {}
    if found:
        type_ids = sorted({type_id for type_id, _ in found.values()})
        rows = await session.execute(
            select(RecordType.id, RecordType.public_submissions).where(
                RecordType.tenant_id == tenant, RecordType.id.in_(type_ids)
            )
        )
        kinds = {int(tid): (config or {}).get("kind") for tid, config in rows.all()}
    return {uuid: (kinds.get(tid), data) for uuid, (tid, data) in found.items()}


def _retired(kind: str | None, data: Any) -> bool:
    """A confirmation attempt that can never resume: the subscriber left
    pending (or the row is no subscriber at all any more)."""
    return kind == KIND_SUBSCRIPTION and (data or {}).get("sm_status") != PENDING


async def prune_deliveries(
    session_factory: Callable[[], Any],
    cutoff: datetime,
    keep: Callable[[], Awaitable[None]] | None = None,
) -> int:
    """Delete the bound tenant's finished attempts (see the module docstring);
    the number of rows deleted."""
    table = SubmissionDelivery
    tenant = bound_tenant()
    completed = func.count(case((table.recipient == COMPLETE, 1)))
    # Belt and braces: ``attempts.complete`` writes the marker only when none
    # is unsent, and pruning checks the same again.
    unsent = func.count(case((and_(table.recipient.not_in(MARKERS), table.sent_at.is_(None)), 1)))
    newest = func.max(func.coalesce(table.sent_at, table.claimed_at))
    session = session_factory()
    try:
        groups = (
            await session.execute(
                select(table.record_uuid, table.attempt, completed, unsent, newest)
                .where(table.tenant_id == tenant)
                .group_by(table.record_uuid, table.attempt)
            )
        ).all()
        if not groups:
            await events.rollback(session)
            return 0
        records = await _records(session, sorted({str(g[0]) for g in groups}))
        await events.rollback(session)  # read-only so far; release the snapshot
    finally:
        await session.close()
    done: list[tuple[str, str]] = []
    for uuid, attempt, complete_rows, open_rows, last in groups:
        uuid = str(uuid)
        if uuid not in records:
            done.append((uuid, attempt))  # verifiably gone: can never resume
            continue
        stamp = _aware(last)
        old = stamp is None or stamp < cutoff
        if old and ((complete_rows and not open_rows) or _retired(*records[uuid])):
            done.append((uuid, attempt))
    deleted = 0
    for start in range(0, len(done), _CHUNK):
        if keep is not None:
            await keep()
        session = session_factory()
        try:
            result = await session.execute(
                sa_delete(table)
                .where(
                    table.tenant_id == tenant,
                    tuple_(table.record_uuid, table.attempt).in_(done[start : start + _CHUNK]),
                )
                .execution_options(synchronize_session=False)
            )
            if keep is not None:
                await keep()
            await events.commit(session)
            deleted += int(result.rowcount or 0)
        except BaseException:
            await events.rollback(session)
            raise
        finally:
            await session.close()
    return deleted
