"""Running a type's pending reindex — out of request, on its own session.

Design doc §8.5 and §8.9. The schema write is one row and is synchronous; the
rebuild over records is not request work, and this repo has no Celery
(``CLAUDE.md`` says so), so "deferred" means a FastAPI background task plus the
resumable ``reindex`` CLI command — :mod:`sm_records.cli`.

That is sufficient only because the operation is idempotent and restartable
(§7.7): every record's rows are deleted and rewritten from ``data``, and
``reindex_pending`` is cleared last, so a crash anywhere leaves the markers set
and a re-run converges. The worst case of a lost background task is a field
that refuses filters until someone runs the command — recoverable, and made
*visible* by the health check in :mod:`sm_records.health`.

**This module commits.** Everything else in the services layer refuses to,
because the framework's ``get_db`` owns the request's transaction. A runner
started from a background task has no request and no ``get_db``: nothing else
would ever commit its session, and the rebuild would roll back silently.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import REINDEX_ALL
from sm_records.index.reindex import (
    clear_pending,
    delete_field_rows,
    pending_map,
    reindex_type,
)
from sm_records.models import Record, RecordType
from sm_records.schema.compile import from_stored
from sm_records.services._common import mark_written, reload, type_resolver
from sm_records.services._payload import display_title, field_defs, lock_type
from sm_records.settings import RecordsSettings

__all__ = ["pending_type_ids", "run_pending", "schedule"]

logger = logging.getLogger(__name__)


async def pending_type_ids(db: AsyncSession) -> list[int]:
    """Every type with at least one ``reindex_pending`` entry.

    Filtered in Python: the column is plain ``JSON``, so "is this object empty"
    is spelled differently on every backend, and there are tens of types rather
    than millions.
    """
    rows = (await db.execute(select(RecordType.id, RecordType.reindex_pending))).all()
    return [int(type_id) for type_id, pending in rows if pending and type_id is not None]


async def _recompute_titles(db: AsyncSession, rtype: RecordType, batch_size: int) -> int:
    """Rebuild every record's denormalised ``display_title`` (§18 Q2).

    Resolved there in favour of the reindex owning it, because this is where
    the batched, resumable machinery already is. Read through ``from_stored``
    so the title comes from the value as the *current* schema reads it — a
    ``number`` that is still stored as the string a ``text`` field wrote.

    The trash is included: a restored record showing the title of a pointer
    that was replaced months ago is exactly the staleness this fixes.
    """
    defs = field_defs(rtype)
    last_id, total = 0, 0
    while True:
        batch = (
            (
                await db.execute(
                    select(Record)
                    .where(Record.type_id == rtype.id, Record.id > last_id)
                    .order_by(Record.id)
                    .limit(batch_size)
                    .execution_options(include_deleted=True)
                )
            )
            .scalars()
            .all()
        )
        if not batch:
            return total
        for record in batch:
            values = from_stored(defs, dict(record.data or {}))
            record.display_title = display_title(rtype, values)
            db.add(record)
            last_id = record.id or last_id
            total += 1
        await db.flush()


async def _clear_rebuilt(
    session: AsyncSession, rtype: RecordType, keys: list[str], started_at_schema: int
) -> None:
    """Clear the markers this run actually rebuilt — see :func:`run_pending`.

    The lock is taken here rather than for the whole run: holding a type's row
    ``FOR UPDATE`` across a rebuild of every record would block every write to
    the type for its duration, and the rebuild is idempotent precisely so it
    does not need that. It is held for the read-modify-write of one JSON
    column, which is the only part that races.
    """
    await lock_type(session, rtype)
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


async def run_pending(db_state, type_id: int, *, settings: RecordsSettings) -> int:
    """Finish whatever ``reindex_pending`` says is outstanding for one type.

    Returns the number of records rebuilt (``0`` when nothing was pending, or
    when the type has gone since the task was scheduled — a deleted type is not
    an error here; its markers went with it).

    The sequence is §8.5's, minus the parts the schema write already did:
    index rows for keys the type no longer declares are deleted outright, every
    record is reprojected through the current definitions — which is what moves
    a retyped field's rows from one index table to the next — titles are
    recomputed if a whole-type rebuild is pending, and only then are the
    markers cleared. Clearing last is what makes an interrupted run safe to
    repeat.

    **Clearing reads the type row again, under the lock, and clears only what
    this run rebuilt.** A rebuild is the longest thing this module does, so a
    second schema change committed by a request while it runs is ordinary, not
    exotic — and that change's marker must survive a run that knew nothing
    about it. If the row's ``schema_version`` moved at all, the fields this run
    reprojected are not the fields the type now declares: nothing is cleared,
    every marker is left for the next run, and the health check surfaces it if
    no run follows. Leaving a marker set is always safe — the operation is
    idempotent — while clearing one that was never rebuilt is not.
    """
    async with db_state.session_factory() as session:
        rtype = (
            (await session.execute(select(RecordType).where(RecordType.id == type_id)))
            .scalars()
            .first()
        )
        if rtype is None:
            return 0
        pending = pending_map(rtype)
        if not pending:
            return 0
        started_at_schema = rtype.schema_version

        keys = list(pending)
        field_keys = [key for key in keys if key != REINDEX_ALL]
        declared = {str(raw.get("key")) for raw in rtype.fields or []}
        removed = [key for key in field_keys if key not in declared]
        if removed:
            await delete_field_rows(session, rtype, removed)

        count = await reindex_type(
            session,
            rtype,
            resolve_type_id=await type_resolver(session),
            batch_size=settings.reindex_batch_size,
            field_keys=field_keys or None,
        )
        if REINDEX_ALL in pending:
            await _recompute_titles(session, rtype, settings.reindex_batch_size)

        await _clear_rebuilt(session, rtype, keys, started_at_schema)
        # The rebuild's own statements are ORM writes, but the row deletes above
        # are core DML, which never fires the listener the framework commits on.
        # This session has no request behind it either way, so say so explicitly.
        mark_written(session)
        await session.commit()
        return count


async def schedule(db_state, type_id: int, settings: RecordsSettings) -> int:
    """The entry point for a FastAPI ``BackgroundTasks`` — ``add_task(schedule,
    db_state, type_id, settings)``.

    Two differences from calling :func:`run_pending` directly, both about
    living outside a request. It takes ``settings`` positionally, so the call
    site reads as a task rather than as a service call; and it swallows its
    exceptions after logging them, because a background task that raises does
    so with the response already sent, where there is nobody to tell. The
    failure is not lost: ``reindex_pending`` stays set, the health check
    degrades on it once it is stale, and the CLI finishes the job.
    """
    try:
        return await run_pending(db_state, type_id, settings=settings)
    except Exception:  # pragma: no cover - defensive; the runner is tested directly
        logger.exception("records: reindex of type %s failed", type_id)
        return 0
