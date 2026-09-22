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

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index.providers import TypeIndex
from sm_records.models import RecordType, tables_for

try:  # pragma: no cover - the constant is the framework's, the fallback is ours
    from simple_module_db.listeners import SESSION_HAS_WRITES_KEY
except ImportError:  # pragma: no cover
    SESSION_HAS_WRITES_KEY = "has_writes"


def role_blocked(rtype: RecordType, roles: Sequence[str] | None) -> bool:
    """Design §10's ``allowed_roles`` narrowing, as a predicate with one owner.

    Three places apply it and they must not drift: ``deps.check_type_roles``
    (the type named in the URL), ``services._lifecycle`` (a type a cascade or
    a ``set_null`` reaches that the URL never names) and the two Phase 4 reads
    — ``services.expand`` and the referrers listing — where a target the
    caller may not see is reported as ``restricted`` rather than resolved.
    A second copy of "does this caller hold one of these roles" is how the
    read path ends up more permissive than the write path.

    ``roles is None`` means "no caller": the CLI, a background task, any path
    with no user behind it, which keeps the unrestricted behaviour. An empty
    list is a caller holding no roles, and a narrowed type blocks them.

    Note what this deliberately does not do: an ``admin`` wildcard is not an
    exception. Narrowing is a list of role names, and a role not on it is
    refused however powerful it is elsewhere (see the README).
    """
    if roles is None:
        return False
    allowed = rtype.allowed_roles or []
    return bool(allowed) and not set(roles).intersection(allowed)


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


async def type_resolver(db: AsyncSession) -> TypeIndex:
    """The ``resolve_type_id`` argument ``write_index`` and the reindex take.

    A :class:`~sm_records.index.providers.TypeIndex` rather than the map's
    ``.get``: it *is* the resolver (it is callable), and it also carries the
    id set the writer checks a provider's ``REF`` entries against — an index
    provider may project rows, not invent references (§7.6).
    """
    return TypeIndex(await type_id_map(db))


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
    """``… SET version = version + 1, updated_at = now WHERE id = :id AND version = :expected``.

    ``True`` when the row was still at ``expected_version``; ``False`` when
    somebody else got there first, which is the caller's 409. See the module
    docstring for why the caller then writes its columns through the ORM.

    **``updated_at`` is written here explicitly, and that is not cosmetic.**
    ``AuditMixin`` declares it ``onupdate=func.now()``, so *any* ``UPDATE`` of
    the row — including this one — carries a value the ORM cannot know.
    SQLAlchemy's answer is to **expire the attribute** on the instance in the
    identity map and re-read it when somebody asks. That re-read is a lazy
    load, and the caller that asks is the synchronous ``record_read`` building
    the response after the endpoint's last ``await`` — so it runs outside the
    async greenlet and raises ``MissingGreenlet``: an unhandled 500 on a write
    that had already done its work (GH: the functional QA's finding 1,
    reproduced 5/5 on Postgres). It only ever surfaced *sometimes* because the
    framework's ``before_flush`` audit listener assigns ``updated_at`` on any
    row it considers modified, which un-expires it — and a write whose columns
    all happen to keep their values (re-saving a form unchanged) is not
    modified, so nothing put the value back.

    Assigning a timestamp here means the column is in ``values()``, so Core
    never applies the ``onupdate`` default, the ORM can evaluate the literal
    into the instance, and **no attribute is left expired by this statement**.
    It is also the honest value: this statement is the write, and it is the
    same ``datetime.now(UTC)`` the audit listener would have used.
    """
    values: dict[str, Any] = {"version": model.version + 1}
    if getattr(model, "updated_at", None) is not None:
        values["updated_at"] = utcnow()
    result = await db.execute(
        sa_update(model)
        .where(model.id == row_id, model.version == expected_version)
        .values(**values)
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
    ``func.count(record.id)`` rather than a bare ``count()`` so the statement
    names the mapper — that is what the framework's soft-delete filter attaches
    to, and without it this would always count the trash. The class comes from
    ``tables_for(rtype)``, so a collection type is counted in its own table
    (Phase 5 §6.3).

    Which count a caller wants is not a detail. "Live" is what an operator is
    shown on a screen; but §16's ``fields`` lock and §8.9's delete
    confirmation are about *content the schema describes*, and a trashed
    record still holds a payload written against those fields and is one
    restore away from being read under them. Both of those pass
    ``include_deleted=True``.
    """
    record = tables_for(rtype).record
    stmt = select(func.count(record.id)).where(record.type_id == rtype.id)
    if include_deleted:
        stmt = stmt.execution_options(include_deleted=True)
    return int((await db.execute(stmt)).scalar_one())


async def record_counts(db: AsyncSession, rtype: RecordType) -> tuple[int, int]:
    """``(live, trashed)`` — the pair every ``TypeRead`` is built from."""
    live = await record_count(db, rtype)
    total = await record_count(db, rtype, include_deleted=True)
    return live, total - live


class PurgedRecord(Protocol):
    """What a purged record leaves behind: the three columns its event needs.

    ``services._lifecycle.purge_type_records`` deletes a whole type set-based
    — one statement per table rather than ten per record — so there is no ORM
    instance afterwards to read a payload from, and there does not need to be:
    a ``RecordPurged`` addresses a record by ``(type_key, uuid)`` exactly as
    the API does, and carries its language and its translation group because
    those are the only facts a subscriber cannot look up once the row is gone.

    A ``Protocol`` rather than a class, because what actually arrives is
    SQLAlchemy's ``Row`` from a three-column select. Naming the shape is what
    keeps ``delete_type``'s signature honest about what it hands back.
    """

    uuid: str
    locale: str
    translation_group: str
