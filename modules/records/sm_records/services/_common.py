"""Pieces every records service shares: the clock, the type-id lookup, and
the optimistic-concurrency guard.

The guard is two statements rather than one, and the reason is not style.
Design §5.1/§8.6 want the update expressed as
``UPDATE … SET version = version + 1 WHERE id = :id AND version = :expected``,
which is a *core* statement — and the framework decides whether to commit the
request's session from an ``after_flush`` listener that core DML never fires
(``simple_module_db.listeners``). A service whose only write was that one
statement would therefore be rolled back at the end of the request. So the
core statement does the guard and the version bump, and the caller then
assigns the new column values onto the ORM object it already holds: that flush
is an ORM flush, the session is marked written, and the object in the identity
map does not go stale behind the caller's back.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import Record, RecordType

try:  # pragma: no cover - the constant is the framework's, the fallback is ours
    from simple_module_db.listeners import SESSION_HAS_WRITES_KEY
except ImportError:  # pragma: no cover
    SESSION_HAS_WRITES_KEY = "has_writes"


def utcnow() -> datetime:
    """Aware UTC. Every timestamp this module writes is aware — the columns
    are ``DateTime(timezone=True)`` and a naive value would index and compare
    differently depending on where it was written."""
    return datetime.now(UTC)


async def type_id_map(db: AsyncSession) -> dict[str, int]:
    """``{type key: id}`` for the whole install.

    The preload behind every ``resolve_type_id``: the index writer's resolver
    is a *synchronous* callable (``index.providers.TypeResolver``), because a
    provider is registered once at import time and cannot await. So the one
    query happens here and the resolver is the resulting dict's ``.get``.
    """
    rows = (await db.execute(select(RecordType.key, RecordType.id))).all()
    return {key: int(type_id) for key, type_id in rows if type_id is not None}


async def type_resolver(db: AsyncSession) -> Callable[[str], int | None]:
    """The ``resolve_type_id`` argument ``write_index`` and the reindex take."""
    return (await type_id_map(db)).get


def mark_written(db: AsyncSession) -> None:
    """Tell the framework this session changed something.

    ``get_db`` commits the request only if the ``after_flush`` listener fired,
    and core DML — the guarded version bump, a purge — never fires it. A
    service whose only statements are core would therefore be rolled back at
    the end of the request, which for a purge means the rows quietly come
    back. Setting the flag the listener sets is the narrowest fix available
    from outside the framework; the fallback key covers a framework build
    that predates the constant, since a published module depends on a *range*
    (CLAUDE.md) and cannot assume the newest one.
    """
    db.info[SESSION_HAS_WRITES_KEY] = True


async def guarded_bump(db: AsyncSession, model: Any, row_id: int, expected_version: int) -> bool:
    """``… SET version = version + 1 WHERE id = :id AND version = :expected``.

    ``True`` when the row was still at ``expected_version``; ``False`` when
    somebody else got there first, which is the caller's 409. See the module
    docstring for why the caller then writes its columns through the ORM.
    """
    result = await db.execute(
        sa_update(model)
        .where(model.id == row_id, model.version == expected_version)
        .values(version=model.version + 1)
    )
    if result.rowcount:
        mark_written(db)
        return True
    return False


async def reload[T](db: AsyncSession, model: type[T], row_id: int) -> T | None:
    """Re-read one row, overwriting what the identity map holds.

    ``populate_existing`` because the caller is asking precisely *because* its
    instance is stale, and a plain select would hand the stale one straight
    back. ``include_deleted`` because the row a conflict wants to show may
    have been trashed by the writer that won the race, and "it is gone" is a
    better answer than ``None`` meaning "no idea".
    """
    stmt = (
        select(model)
        .where(model.id == row_id)
        .execution_options(include_deleted=True, populate_existing=True)
    )
    return (await db.execute(stmt)).scalars().first()


async def record_count(
    db: AsyncSession, rtype: RecordType, *, include_deleted: bool = False
) -> int:
    """How many records the type holds — live only, or the trash as well.

    Not a column: the previous draft denormalised it and §5 removed it,
    because a ``COUNT`` over an indexed column is cheap and cannot go stale.
    ``func.count(Record.id)`` rather than a bare ``count()`` so the statement
    names the mapper — that is what the framework's soft-delete filter attaches
    to, and without it this would always count the trash.

    Which count a caller wants is not a detail. "Live" is what an operator is
    shown on a screen; but §16's ``fields`` lock and §8.9's delete
    confirmation are about *content the schema describes*, and a trashed
    record still holds a payload written against those fields and is one
    restore away from being read under them. Both of those pass
    ``include_deleted=True``.
    """
    stmt = select(func.count(Record.id)).where(Record.type_id == rtype.id)
    if include_deleted:
        stmt = stmt.execution_options(include_deleted=True)
    return int((await db.execute(stmt)).scalar_one())


async def record_counts(db: AsyncSession, rtype: RecordType) -> tuple[int, int]:
    """``(live, trashed)`` — the pair every ``TypeRead`` is built from."""
    live = await record_count(db, rtype)
    total = await record_count(db, rtype, include_deleted=True)
    return live, total - live
