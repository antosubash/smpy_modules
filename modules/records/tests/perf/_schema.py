"""Bringing a *reused* perf database's schema up to what the model declares.

``perf_db`` keeps its seeded SQLite file between runs — seeding is the slowest
thing in this directory by an order of magnitude — and ``create_all`` is
``checkfirst`` per *table*, so a file seeded before an additive migration is
skipped whole. These two put back what such a file is missing, which is the
difference between measuring the current schema and a ``no such column`` on
the first read. Split from ``conftest.py`` for the 300-line cap.
"""

from __future__ import annotations

from typing import Any

from sm_records.models import Base
from sqlalchemy import inspect


def create_missing_indexes(conn: Any) -> None:
    """Add any index the model declares that the database does not have yet.

    ``create_all`` is ``checkfirst`` per *table*: a database seeded before a
    revision added an index to an existing table is skipped whole, so the
    suite would keep measuring the old schema against the new code and report
    the new indexes as doing nothing. The seeded file is reused across runs on
    purpose (it is the slowest thing here), which is exactly the case this
    covers — and creating an index that is already there is a no-op, so it is
    also safe on a fresh one.

    **Backend-independent since S2.** It used to read ``sqlite_master`` and
    return early on anything else, on the grounds that a Postgres run is always
    against a database seeded by the same revision. That was true until a
    revision added an index and the before/after pair had to be taken on one
    Postgres database — which is precisely what this function exists for.
    ``inspect`` answers the same question on both backends.

    **And it ``ANALYZE``s what it touched**, which is not tidiness. A new index
    with no ``sqlite_stat1`` row is not "unknown" to SQLite's planner, it is
    *assumed to be very selective* — so on a database whose other indexes were
    analysed by the seeder it wins every lookup it is eligible for, and a list
    page that took 1.1 ms takes 26.5 ms driving from the wrong one. That is a
    property of a half-analysed database, not of the index, and a suite that
    left the file in that state would be measuring a deployment nobody has:
    the revision that creates these indexes runs ``ANALYZE`` too
    (``c4a17b9de0f2``), for the same reason.
    """
    inspector = inspect(conn)
    created: set[str] = set()
    for table in Base.metadata.tables.values():
        if not inspector.has_table(table.name):
            continue
        have = {index["name"] for index in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in have:
                index.create(conn)
                created.add(table.name)
    if created and conn.dialect.name == "sqlite":
        for name in sorted(created):
            conn.exec_driver_sql(f"ANALYZE {name}")


def create_missing_columns(conn: Any) -> None:
    """Add any **column** the model declares that a reused database lacks.

    The sibling of :func:`create_missing_indexes`, and for the same reason:
    ``create_all`` is ``checkfirst`` per *table*, so a file seeded before an
    additive migration is skipped whole and every later query selects a column
    the file does not have — which is a ``no such column`` on the first read,
    not a wrong measurement. Phase 5 §6.2's nullable ``records_type.collection``
    is what made this concrete.

    A ``NOT NULL`` column is recovered too, when it declares a scalar default —
    the rows already in the file need a value, and the column's own default is
    the same answer its migration gives them (``records_type.show_in_menu``
    adds ``server_default=false()`` for exactly this reason). Anything else —
    a ``NOT NULL`` column with no default, a changed type, a dropped column —
    means the cached database is the wrong dataset and should be deleted.
    """
    if conn.dialect.name != "sqlite":
        return
    for table in Base.metadata.tables.values():
        rows = conn.exec_driver_sql(f"PRAGMA table_info('{table.name}')").fetchall()
        if not rows:
            continue
        have = {row[1] for row in rows}
        for column in table.columns:
            if column.name in have:
                continue
            ddl = column.type.compile(dialect=conn.dialect)
            if not column.nullable:
                literal = _default_literal(column)
                if literal is None:
                    continue
                ddl = f"{ddl} NOT NULL DEFAULT {literal}"
            conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl}')


_LITERALS = {
    bool: lambda value: "1" if value else "0",
    int: str,
    float: repr,
    str: lambda value: "'{}'".format(value.replace("'", "''")),
}


def _default_literal(column: Any) -> str | None:
    """The column's Python-side default as SQL, or ``None`` if it has none it
    can express — a callable (``list``, ``dict``) or a type not listed."""
    value = getattr(column.default, "arg", None)
    render = _LITERALS.get(type(value))
    return render(value) if render is not None else None
