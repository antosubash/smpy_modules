"""``INSERT … ON CONFLICT DO NOTHING`` on the two backends the module supports."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Table
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["affected_rows", "insert_ignore"]

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
    dialect = session.get_bind().dialect.name
    insert = _INSERTS.get(dialect)
    if insert is None:
        raise ValueError(f"insert_ignore supports postgresql and sqlite, not {dialect}")
    inserted = 0
    for start in range(0, len(rows), _CHUNK):
        chunk = list(rows[start : start + _CHUNK])
        stmt = insert(table).values(chunk).on_conflict_do_nothing(index_elements=list(conflict))
        result = await session.execute(stmt)
        inserted += affected_rows(result, dialect)
    return inserted
