"""``INSERT … ON CONFLICT`` on the two backends the module supports.

:func:`insert_ignore` is ``DO NOTHING``. :func:`upsert_newest` is ``DO
UPDATE``, keeping the later of the stored and the offered time, in one
statement per chunk, so a row deleted by a concurrent writer is simply
inserted again rather than lost between an insert and a separate update.

Both return exactly how many rows were *inserted*:

* ``DO NOTHING``: the driver's rowcount (skipped rows are not counted).
* ``DO UPDATE`` on Postgres: ``RETURNING (xmax = 0)``. A freshly inserted
  tuple has no deleting/locking transaction (``xmax = 0``); a row the conflict
  arm updated carries this transaction's id there. Same statement, so the
  count is exact under concurrent writers at any isolation level.
* ``DO UPDATE`` on SQLite has no such marker (its rowcount counts updates
  too). Each chunk first runs the ``DO NOTHING`` insert, whose rowcount is the
  exact insert count, then the ``DO UPDATE``. The first is a write, so it opens
  SQLite's write transaction (the driver issues ``BEGIN`` before an
  ``INSERT``) and takes its single write lock; no other connection can insert
  or delete a row before this transaction ends, so the second statement
  inserts nothing and only refreshes. (A ``SELECT`` count first would not be
  enough: the driver does not begin a transaction for a read, so another
  writer could commit in between.)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Table, case, func, literal_column
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["affected_rows", "insert_ignore", "upsert_newest"]

_INSERTS: dict[str, Any] = {"postgresql": postgresql.insert, "sqlite": sqlite.insert}

# One statement per chunk keeps SQLite under its bound-parameter limit.
_CHUNK = 500


def affected_rows(result: Any, dialect: str) -> int:
    """``result.rowcount``, failing loudly on the driver's ``-1`` ("unknown")."""
    count = result.rowcount
    if count is None or count < 0:
        raise RuntimeError(f"the {dialect} driver did not report a row count")
    return int(count)


async def insert_ignore(
    session: AsyncSession,
    table: Table,
    rows: Sequence[dict[str, Any]],
    *,
    conflict: Sequence[str],
) -> int:
    """Insert ``rows``, skipping any whose ``conflict`` columns already exist.

    Returns how many rows were inserted. A Core statement: the caller pins
    ``tenant_id`` in every row, since the tenant mixin stamps ORM flushes only.
    Does not commit.
    """
    dialect, insert = _dialect(session)
    inserted = 0
    for chunk in _chunks(rows):
        inserted += await _ignore(session, insert, table, chunk, conflict, dialect)
    return inserted


async def upsert_newest(
    session: AsyncSession,
    table: Table,
    rows: Sequence[dict[str, Any]],
    *,
    conflict: Sequence[str],
    time_column: str,
    follow: Sequence[str],
) -> int:
    """Insert ``rows``; on a ``conflict`` keep the later ``time_column``.

    An existing row gets ``time_column = max(stored, offered)``, and each
    ``follow`` column takes the offered value only when the offered time is
    strictly later. Returns how many rows were inserted (see the module
    docstring for how, per dialect). Same caller contract as
    :func:`insert_ignore`.
    """
    dialect, insert = _dialect(session)
    later = func.greatest if dialect == "postgresql" else func.max  # SQLite's scalar max()
    inserted = 0
    for chunk in _chunks(rows):
        stmt = insert(table).values(chunk)
        stored, offered = table.c[time_column], stmt.excluded[time_column]
        newer = offered > stored
        sets: dict[str, Any] = {time_column: later(stored, offered)}
        for name in follow:
            sets[name] = case((newer, stmt.excluded[name]), else_=table.c[name])
        stmt = stmt.on_conflict_do_update(index_elements=list(conflict), set_=sets)
        if dialect == "postgresql":
            flags = (await session.execute(stmt.returning(literal_column("(xmax = 0)")))).scalars()
            inserted += sum(1 for fresh in flags if fresh)
        else:
            fresh = await _ignore(session, insert, table, chunk, conflict, dialect)
            inserted += fresh
            if fresh < len(chunk):
                await session.execute(stmt)
    return inserted


def _dialect(session: AsyncSession) -> tuple[str, Any]:
    dialect = session.get_bind().dialect.name
    insert = _INSERTS.get(dialect)
    if insert is None:
        raise ValueError(f"upserts support postgresql and sqlite, not {dialect}")
    return dialect, insert


def _chunks(rows: Sequence[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    return [list(rows[i : i + _CHUNK]) for i in range(0, len(rows), _CHUNK)]


async def _ignore(
    session: AsyncSession,
    insert: Any,
    table: Table,
    chunk: list[dict[str, Any]],
    conflict: Sequence[str],
    dialect: str,
) -> int:
    stmt = insert(table).values(chunk).on_conflict_do_nothing(index_elements=list(conflict))
    return affected_rows(await session.execute(stmt), dialect)
