"""Running a type's pending reindex — out of request, on its own session.

Design doc §8.5 and §8.9. The schema write is one row and is synchronous; the
rebuild over records is not request work, and this repo has no Celery
(``CLAUDE.md`` says so), so "deferred" means a job queued with
:func:`sm_records.deferred.defer` plus the resumable ``reindex`` CLI command
— :mod:`sm_records.cli`. Not FastAPI's ``BackgroundTasks``, which runs *inside*
the scheduling request's dependency teardown and therefore inside its still-open
transaction; :mod:`sm_records.deferred` has the ordering and what it cost.

That is sufficient only because the operation is idempotent and restartable
(§7.7): every record's rows are deleted and rewritten from ``data``, and
``reindex_pending`` is cleared last, so a crash anywhere leaves the markers set
and a re-run converges. The worst case of a lost job is a field that refuses
filters until someone runs the command — recoverable, and made *visible* by the
health check in :mod:`sm_records.health`.

**This module commits**, per batch and again at the end. Everything else in the
services layer refuses to, because the framework's ``get_db`` owns the request's
transaction. A runner started from a deferred job has no request and no
``get_db``: nothing else would ever commit its session, and the rebuild would
roll back silently.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import REINDEX_ALL
from sm_records.index._analyze import analyze_tables, index_table_names
from sm_records.index.reduce_rebuild import rebuild_type
from sm_records.index.reindex import (
    clear_pending,
    delete_field_rows,
    pending_map,
    reindex_type,
)
from sm_records.models import RecordType, tables_for
from sm_records.services._claims import lock_type
from sm_records.services._common import mark_written, reload, type_resolver
from sm_records.services._titles import recompute_titles
from sm_records.settings import RecordsSettings

__all__ = ["pending_type_ids", "run_pending", "schedule"]

logger = logging.getLogger(__name__)

#: Backoff between attempts when the database refuses the rebuild's writes
#: because somebody else is holding the write lock. Bounded and short: the
#: rebuild is idempotent and restartable, so giving up is a delay rather than
#: damage, and a run that keeps a pool connection busy for minutes is worse
#: than one the CLI or the next schema change finishes.
_LOCK_RETRY_DELAYS: tuple[float, ...] = (0.1, 0.5, 2.0)

#: What SQLite says when it loses the race for its single write lock; the
#: table-level wording is what the same contention looks like from an
#: attached/temp table. Both are transient, and neither is a bug in the SQL.
_LOCKED_MESSAGES = ("database is locked", "database table is locked")


def _is_locked(exc: OperationalError) -> bool:
    text = str(exc.orig or exc).lower()
    return any(message in text for message in _LOCKED_MESSAGES)


async def pending_type_ids(db: AsyncSession) -> list[int]:
    """Every type with at least one ``reindex_pending`` entry.

    Filtered in Python: the column is plain ``JSON``, so "is this object empty"
    is spelled differently on every backend, and there are tens of types rather
    than millions.
    """
    rows = (await db.execute(select(RecordType.id, RecordType.reindex_pending))).all()
    return [int(type_id) for type_id, pending in rows if pending and type_id is not None]


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
    """:func:`_run_pending_once`, retried while the database is merely busy.

    SQLite takes one writer at a time, so a rebuild that overlaps any other
    write — a record saved from another tab, a second schema change, the CLI —
    can lose the race and come back ``database is locked`` rather than doing
    nothing. That is contention, not failure: the run is restarted from the
    top on a fresh session, which is safe because the whole operation is
    idempotent (§7.7).

    Attempts are bounded. When they run out the error is raised, with the
    markers left exactly as they were — pending, which is the state a rebuild
    that never ran is supposed to be in, and which the health check of §8.9
    surfaces once it is stale.
    """
    for attempt, delay in enumerate(_LOCK_RETRY_DELAYS):
        try:
            return await _run_pending_once(db_state, type_id, settings=settings)
        except OperationalError as exc:
            if not _is_locked(exc):
                raise
            logger.warning(
                "records: reindex of type %s found the database locked "
                "(attempt %d/%d); retrying in %.2fs",
                type_id,
                attempt + 1,
                len(_LOCK_RETRY_DELAYS) + 1,
                delay,
            )
            await asyncio.sleep(delay)
    try:
        return await _run_pending_once(db_state, type_id, settings=settings)
    except OperationalError as exc:
        if not _is_locked(exc):
            raise
        logger.warning(
            "records: reindex of type %s gave up after %d locked-database attempts; "
            "its markers stay pending for the next run or the CLI",
            type_id,
            len(_LOCK_RETRY_DELAYS) + 1,
        )
        raise


async def _run_pending_once(db_state, type_id: int, *, settings: RecordsSettings) -> int:
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
            # Nothing is pending for the *map* indexes — but a reduce index
            # carries no marker and never will: registering or changing a spec
            # is the host deploying code, not a schema edit this module can
            # see (Phase 5 §5.2). So the operator who pressed "reindex", or
            # ran the CLI against this type, still has work here, and it is
            # this. With no spec registered it issues no statements at all.
            if await rebuild_type(session, rtype, batch_size=settings.reindex_batch_size):
                mark_written(session)
                await session.commit()
            return 0
        started_at_schema = rtype.schema_version

        keys = list(pending)
        field_keys = [key for key in keys if key != REINDEX_ALL]
        declared = {str(raw.get("key")) for raw in rtype.fields or []}
        removed = [key for key in field_keys if key not in declared]
        if removed:
            await delete_field_rows(session, rtype, removed)

        touched: set[str] = set(index_table_names(tables_for(rtype))) if removed else set()
        count = await reindex_type(
            session,
            rtype,
            resolve_type_id=await type_resolver(session),
            batch_size=settings.reindex_batch_size,
            field_keys=field_keys or None,
            touched=touched,
            # Commit per batch. SQLite has one write lock for the whole file,
            # so a rebuild that held its transaction for every record of a big
            # type would refuse every concurrent write for that whole time;
            # a partial rebuild is safe here precisely because the markers are
            # cleared last, so an interrupted run is repeated rather than lost.
            after_batch=session.commit,
        )
        if REINDEX_ALL in pending:
            await recompute_titles(session, rtype, settings.reindex_batch_size)

        await _clear_rebuilt(session, rtype, keys, started_at_schema)
        # Every statement the rebuild issues is core DML, which never fires the
        # listener the framework commits on. This session has no request behind
        # it either way, so say so explicitly.
        mark_written(session)
        await session.commit()

        # After the commit, not inside it: ``ANALYZE`` takes the write lock,
        # and the rebuild has no reason to keep holding one while it runs. The
        # index of this type was just rewritten wholesale, which is the moment
        # the planner's statistics are most out of date and cheapest to refresh
        # — see :mod:`sm_records.index._analyze`.
        if touched:
            await analyze_tables(session, touched)
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
