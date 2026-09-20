"""Refreshing the query planner's statistics for the module's own tables.

The one place this module writes raw SQL, because ``ANALYZE`` has no Core
construct — and the names it is given come from ``__tablename__`` constants,
never from a caller.

Why it exists at all: on SQLite with no ``sqlite_stat1``, a filter on a
``number``, ``date``, ``datetime`` or ``boolean`` field gets a plan whose cost
is the size of the type rather than the size of the match, and a single list
page over 45,000 records took minutes. The semi-join in
:mod:`sm_records.index.query` removes the planner's chance to get that wrong,
and statistics are what make the rest of its choices — which index to drive an
ordered scan from, which side of a join to start on — informed rather than
guessed.

**Never on a request path.** ``ANALYZE`` takes the write lock, briefly but
really. The two moments a module can legitimately claim are the ones where it
has just rewritten its own index wholesale: the end of a completed reindex
(:mod:`sm_records.services.reindex_runner`) and the end of a seeding run
(:mod:`sm_records.seed.runner`). Both are explicitly out-of-request work.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import TableSet, table_set, table_sets
from sm_records.models._base import TYPE_TABLE

logger = logging.getLogger(__name__)

__all__ = ["analyze_tables", "index_table_names", "owned_table_names"]


def index_table_names(tables: TableSet | None = None) -> frozenset[str]:
    """The six kind tables of one table set — what a reindex rewrites.

    A function of the set rather than a module constant since Phase 5 §6: a
    rebuild of a collection type rewrites that collection's tables, and
    ``ANALYZE``-ing the global ones instead would refresh statistics for rows
    nothing touched while leaving the stale ones stale. ``None`` is the global
    set, for a caller with no type in hand.
    """
    return frozenset(str(table.__tablename__) for table in (tables or table_set(None)).index_tables)


def owned_table_names() -> frozenset[str]:
    """Everything a bulk load touches that a query later plans against —
    **every** declared table set's documents and index rows, plus the shared
    type table. The seeder writes across whatever collections its types name,
    so this cannot be narrowed to one of them."""
    names = {TYPE_TABLE}
    for tables in table_sets():
        names.add(str(tables.record.__tablename__))
        names |= index_table_names(tables)
    return frozenset(names)


async def analyze_tables(db: AsyncSession, tables: Iterable[str]) -> None:
    """``ANALYZE`` the named tables. SQLite only, best effort.

    A failure is logged and swallowed. Statistics are an optimisation: a
    rebuild that finished correctly must not be reported as failed because the
    statistics pass lost a race for the write lock — and in particular must not
    be *retried from the top* by
    :func:`sm_records.services.reindex_runner.run_pending`, which reads a
    locked database as "run the whole thing again".

    Stops at the first refusal rather than trying the remaining tables: they
    share one lock, so what stopped the first will stop the rest.
    """
    if db.get_bind().dialect.name != "sqlite":
        return
    for name in sorted(set(tables)):
        try:
            await db.execute(text(f"ANALYZE {name}"))
        except OperationalError as exc:  # pragma: no cover - contention only
            logger.warning("records: ANALYZE %s did not run (%s)", name, exc)
            return
