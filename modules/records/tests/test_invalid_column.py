"""``invalid_since`` is a column of every record table, not just the global one.

The stored half of §8.3's "marked, not hidden" (see
``models/_record.py``). ``tables_for()`` builds a collection's document table
from the same factory as the global one, so the column arrives everywhere for
free — and that is exactly the kind of "for free" worth a test, because the
grammar's ``invalid`` filter compiles to this column against whichever table
set the type lives in, and a set missing it is a 500 rather than a wrong answer.

``test_collections_ddl`` compares the whole DDL of both sets and would also
catch a divergence; this names the column, its nullability and its index, so a
failure says what broke rather than printing two ``CREATE TABLE``s.
"""

from __future__ import annotations

from sm_records.models import table_sets


def test_every_table_set_carries_the_column():
    for tables in table_sets():
        table = tables.record.__table__
        column = table.c.get("invalid_since")
        assert column is not None, f"{table.name} has no invalid_since"
        # Nullable with no default: ``NULL`` is "nothing has found this record
        # wanting", which is the honest state of every row until a scan runs.
        assert column.nullable and column.server_default is None
        assert column.type.timezone is True


def test_every_table_set_indexes_it_under_its_own_name():
    """Index names are schema-global on Postgres, so a collection's copy is
    named after its own table — the rule every index here follows."""
    for tables in table_sets():
        table = tables.record.__table__
        name = f"ix_{table.name}_invalid_since"
        assert name in {index.name for index in table.indexes}
