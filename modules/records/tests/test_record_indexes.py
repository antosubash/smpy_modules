"""The document table's descending indexes — S2.

F5 gave every sortable fixed column a ``(type_id, <column>, id)`` index, and
``index/_sorting`` drops ``NULLS LAST`` only from the columns the mapper says
are ``NOT NULL``. The three that keep it need a second index declared the way
their descending page asks for it, because a btree stores one ordering and
``DESC NULLS LAST`` is neither direction of an ascending one — on Postgres the
index was simply not used and the whole type was sorted to return 25 rows.

Three things have to stay true and none of them is checked anywhere else: the
list of nullable columns has to track the *mapper*, the DDL has to be accepted
by both backends (SQLite has no ``NULLS`` clause in ``CREATE INDEX`` at all),
and every table set has to carry the indexes under its own names.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sm_records.index._fixed import NOT_NULL_FIXED_COLUMNS, SORT_INDEXED_FIXED_COLUMNS
from sm_records.models import table_sets
from sm_records.models._record_args import DESCENDING_SORT_COLUMNS, descending_index_names
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateIndex


def test_the_descending_list_is_exactly_the_nullable_sortable_columns():
    """``_record_args`` writes the list out because it runs before the columns
    exist; this is what stops the two from drifting.

    A column that becomes ``NOT NULL`` keeps an index it no longer needs, and
    one that becomes nullable silently loses the index its descending sort
    depends on — the second is the bug S2 was, arriving quietly.
    """
    assert set(DESCENDING_SORT_COLUMNS) == SORT_INDEXED_FIXED_COLUMNS - NOT_NULL_FIXED_COLUMNS


@pytest.mark.parametrize("column", DESCENDING_SORT_COLUMNS)
def test_the_ddl_is_descending_on_both_backends_and_nulls_last_only_on_postgres(column):
    """SQLite rejects ``NULLS LAST`` inside ``CREATE INDEX`` outright
    (``unsupported use of NULLS LAST``) and does not need it: it sorts ``NULL``
    smallest, so ``DESC`` already puts them last. Postgres stores the ordering
    and needs it spelled out."""
    table = table_sets()[0].record.__table__
    name = f"ix_{table.name}_type_{column.removesuffix('_at')}_desc"
    (index,) = [item for item in table.indexes if item.name == name]
    on_pg = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    on_sqlite = str(CreateIndex(index).compile(dialect=sqlite.dialect()))
    assert f"{column} DESC NULLS LAST" in on_pg, on_pg
    assert f"{column} DESC" in on_sqlite and "NULLS" not in on_sqlite, on_sqlite
    assert on_pg.rstrip().endswith("id DESC)") and on_sqlite.rstrip().endswith("id DESC)")


def test_sqlite_accepts_the_ddl():
    """The compile above is not the test — a dialect can render a string the
    database then refuses, which is exactly what ``DESC NULLS LAST`` does on
    SQLite. This creates the real tables."""
    engine = sa.create_engine("sqlite://")
    from sm_records.models import Base

    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        rows = dict(
            conn.exec_driver_sql(
                "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
            ).all()
        )
    for name in descending_index_names("records_record"):
        assert name in rows, f"{name} was not created"
        assert "DESC" in rows[name] and "NULLS" not in rows[name], rows[name]


def test_every_table_set_carries_them_under_its_own_names():
    """Index names are schema-global on Postgres, so a collection's copies are
    named after its own table — the same rule the slug index follows."""
    for tables in table_sets():
        table = tables.record.__table__
        have = {index.name for index in table.indexes}
        for name in descending_index_names(table.name):
            assert name in have, f"{table.name} is missing {name}"
