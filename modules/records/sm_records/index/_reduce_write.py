"""The statements that move a stored reduce group, and the delta that picks them.

Split from :mod:`sm_records.index.reduce` along the seam
``providers``/``_registry`` already draws in this package: that module is the
*fold* — a spec, and what one record contributes to it — and this one is the
**SQL that stores it**. Keeping them apart is what stops the arithmetic rule
("the database adds, never Python") drifting from the thing it protects.

Nothing here commits. The framework's session commits the request if — and
only if — something was written, so these statements are part of whatever
write called them and roll back with it. They are **core DML**, which does not
fire the framework's ``after_flush`` listener, so a caller whose *only* writes
are these must ``mark_written`` itself; every caller today writes a record in
the same transaction and therefore already has.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index.reduce import contribution, reduce_specs
from sm_records.models import IndexReduce, Record, RecordType

logger = logging.getLogger(__name__)

__all__ = ["apply_delta", "bump", "drop_type_rows", "stored_rows"]


async def bump(
    db: AsyncSession,
    type_id: int,
    key: str,
    group: str,
    *,
    count_delta: int,
    sum_delta: Decimal | None,
    now: datetime,
) -> None:
    """Apply one group's delta: ``count += dc``, ``sum += dv``.

    One statement in the ordinary case. The ``UPDATE`` is the whole mechanism
    — the database does the arithmetic, so a lost increment is not expressible
    — and it matching no row is the *only* signal that this is the group's
    first sight, which is when the second statement (the insert) happens. A
    racing writer that inserted the same group between the two turns that
    insert into an ``IntegrityError`` on the unique index; the savepoint keeps
    the outer transaction alive and the ``UPDATE`` is simply retried, which now
    finds the row the other writer wrote.

    The delete is issued only when the delta was negative, so the ordinary
    write pays nothing for it, and it is guarded by ``count <= 0`` rather than
    by reading the row back — a group is removed when it is empty, and the
    database is the only thing that knows whether it now is.
    """
    result = await db.execute(_increment(type_id, key, group, count_delta, sum_delta, now))
    if not result.rowcount:
        if count_delta <= 0:
            # Nothing to decrement: the group was never counted. Inserting a
            # negative row would turn one missing increment into a permanently
            # wrong stored aggregate, so the drift is left for the verifier.
            logger.warning(
                "records: reduce %r has no stored row for group %r on type %s to decrement; "
                "run `python -m sm_records.cli reindex --verify`",
                key,
                group,
                type_id,
            )
            return
        try:
            async with db.begin_nested():
                await db.execute(
                    insert(IndexReduce).values(
                        type_id=type_id,
                        key=key,
                        group_value=group,
                        count=count_delta,
                        sum=sum_delta,
                        updated_at=now,
                    )
                )
        except IntegrityError:
            await db.execute(_increment(type_id, key, group, count_delta, sum_delta, now))
    if count_delta < 0:
        await db.execute(
            delete(IndexReduce).where(
                IndexReduce.type_id == type_id,
                IndexReduce.key == key,
                IndexReduce.group_value == group,
                IndexReduce.count <= 0,
            )
        )


def _increment(type_id: int, key: str, group: str, dc: int, dv: Decimal | None, now: datetime):
    values: dict[str, Any] = {"count": IndexReduce.count + dc, "updated_at": now}
    if dv is not None:
        # ``func.coalesce`` is not needed: a spec either declares a value for
        # every record or for none, so a row of a value-carrying spec always
        # has a non-null ``sum``.
        values["sum"] = IndexReduce.sum + dv
    return (
        sa_update(IndexReduce)
        .where(
            IndexReduce.type_id == type_id,
            IndexReduce.key == key,
            IndexReduce.group_value == group,
        )
        .values(**values)
    )


async def apply_delta(
    db: AsyncSession,
    rtype: RecordType,
    *,
    before: Record | None,
    after: Record | None,
    now: datetime,
) -> None:
    """Move every registered spec's rows from ``before`` to ``after``.

    ``None`` on either side means "this record did not / does not count":
    a create has no ``before``, a trash has no ``after``, a restore has no
    ``before`` again (a trashed record is not counted, so bringing it back is
    an arrival), and a purge of an already-trashed record has neither — which
    is why it issues no statement at all. The transitions are listed in the
    README and each one has its own test.

    A spec whose contribution is unchanged costs **zero** statements: the
    common edit does not touch the group it is in and the database is not told
    about it.
    """
    for spec in reduce_specs():
        old = contribution(spec, before, rtype) if before is not None else None
        new = contribution(spec, after, rtype) if after is not None else None
        if old == new:
            continue
        deltas: dict[str, tuple[int, Decimal | None]] = {}
        if old is not None:
            deltas[old[0]] = (-1, None if spec.value is None else -old[1])
        if new is not None:
            count, amount = deltas.get(new[0], (0, None if spec.value is None else Decimal(0)))
            deltas[new[0]] = (count + 1, None if spec.value is None else (amount or 0) + new[1])
        for group, (count_delta, sum_delta) in deltas.items():
            if count_delta == 0 and not sum_delta:
                continue
            await bump(
                db,
                rtype.id,
                spec.key,
                group,
                count_delta=count_delta,
                sum_delta=sum_delta,
                now=now,
            )


async def drop_type_rows(db: AsyncSession, type_id: int, key: str | None = None) -> int:
    """Delete a type's stored groups — one spec's, or all of them.

    The rebuild's first half, and what a type delete does: rows here have no
    foreign key to cascade through (:mod:`sm_records.models._reduce` says
    why), so removing them is always explicit.
    """
    stmt = delete(IndexReduce).where(IndexReduce.type_id == type_id)
    if key is not None:
        stmt = stmt.where(IndexReduce.key == key)
    result = await db.execute(stmt)
    return result.rowcount or 0


async def stored_rows(db: AsyncSession, type_id: int, key: str) -> list[IndexReduce]:
    """Every stored group of one spec on one type, unordered."""
    stmt = select(IndexReduce).where(IndexReduce.type_id == type_id, IndexReduce.key == key)
    return list((await db.execute(stmt)).scalars().all())
