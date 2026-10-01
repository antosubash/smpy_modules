"""The document table's indexes — every one of them, named after its table.

Split out of :mod:`sm_records.models._record` for the 300-line cap, along the
seam the factory already drew: that module declares the *columns* a record
has, and this one declares what the database is asked to keep sorted about
them. Both are called once per table set (Phase 5 §6), so a collection's
document table carries exactly these indexes under exactly these names with
its own prefix — which is what ``tests/test_collections_ddl.py`` compares.

The names are derived from the table rather than written out because two of
them are read back by name elsewhere (:class:`~sm_records.models._record_tables.RecordTables`)
and because index names are schema-global on Postgres:
``ix_records_record_type_slug`` can exist exactly once, so a collection's copy
has to be spelled from its own prefix or the second ``CREATE INDEX`` fails.

The longest identifier any table set builds is one of these —
``ix_<prefix>record_type_status_position`` — and it is what
:data:`sm_records.constants.MAX_COLLECTION_NAME_LEN` is measured against, so a
suffix here that grows shortens the longest collection name a host may declare.
``tests/test_collections_name_limit.py`` fails rather than the host's next
migration. Foreign-key names are longer still and are *not* what the limit
bounds: the framework's naming convention spells both table names into one
identifier, so every collection's index-to-document keys are past 63 and
SQLAlchemy's preparer hash-truncates them at DDL time. Nothing disagrees about
that — Alembic matches foreign keys by column signature, and a migration
truncates identically — but a hand-written ``DROP CONSTRAINT`` has to use the
truncated spelling, not the logical one.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKeyConstraint, Index, Table, text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import UnaryExpression

from sm_records.models._base import TYPE_TABLE

__all__ = [
    "DESCENDING_SORT_COLUMNS",
    "add_descending_indexes",
    "descending_index_names",
    "record_args",
]

DESCENDING_SORT_COLUMNS: tuple[str, ...] = ("published_at", "slug", "updated_at")
"""The sortable fixed columns a record may have **no value for**.

Each gets a *second* index, ordered the way a descending page on it asks — see
:func:`record_args`. Written out rather than derived because this module runs
while ``__table_args__`` is being built, i.e. before the columns exist, so it
cannot read nullability off the mapper the way
:data:`sm_records.index._fixed.NOT_NULL_FIXED_COLUMNS` does.
``tests/test_record_indexes.py`` is what keeps the two in step: it fails if a
column becomes nullable, or stops being, without this list moving.
"""


def _short(name: str) -> str:
    """``published_at`` -> ``published`` — the spelling the ascending indexes
    already use, so the pair reads as a pair."""
    return name.removesuffix("_at")


def descending_index_names(table: str) -> tuple[str, ...]:
    """The descending indexes one table set carries, in declaration order.

    Exported because the revision that creates them asks for them by name
    rather than spelling them a second time: index names are schema-global on
    Postgres, so each table set's copies are named after *its* table, and a
    migration that hard-coded the global spellings would create one index and
    miss every collection's."""
    return tuple(f"ix_{table}_type_{_short(name)}_desc" for name in DESCENDING_SORT_COLUMNS)


class _DescNullsLast(UnaryExpression):
    """``<column> DESC NULLS LAST`` inside an index definition, per dialect.

    Postgres stores an ordering in the btree, and ``DESC NULLS LAST`` is
    neither direction of the ascending ``(type_id, col, id)`` index: a btree
    holding ``ASC NULLS LAST`` yields ``DESC NULLS FIRST`` read backwards, so
    the planner ignored it and sorted the whole type instead (S2). Declared
    this way the index *is* the order the page asks for.

    SQLite has no ``NULLS`` clause in ``CREATE INDEX`` at all — the statement
    is a hard ``unsupported use of NULLS LAST`` — and it needs none: SQLite
    sorts ``NULL`` smallest, so a plain ``DESC`` already puts them last and the
    two spellings describe the same index.

    A compiled element rather than ``text()`` because ``text()`` is one string
    on every backend and these two backends need two. A subclass of
    :class:`~sqlalchemy.sql.elements.UnaryExpression`, and not of
    ``ColumnElement``, for a reason that is entirely about **Alembic**: it
    unwraps a ``UnaryExpression`` to decide whether an index is
    "expression-based", and an index it calls expression-based gets an
    *approximate* signature — the columns it could find, which for an opaque
    element is none of them. Autogenerate then compares ``('type_id',)``
    against the three columns the database reports and proposes to drop and
    recreate these indexes on every run, for ever. Wrapping the real column in
    a ``UnaryExpression`` makes the index an ordinary three-column one to
    everything except the DDL compiler.
    """

    inherit_cache = True

    def __init__(self, element: Any) -> None:
        super().__init__(element, modifier=operators.desc_op)


@compiles(_DescNullsLast)
def _render_desc_nulls_last(element: _DescNullsLast, compiler: Any, **kw: Any) -> str:
    return f"{compiler.process(element.element, **kw)} DESC NULLS LAST"


@compiles(_DescNullsLast, "sqlite")
def _render_desc_sqlite(element: _DescNullsLast, compiler: Any, **kw: Any) -> str:
    return f"{compiler.process(element.element, **kw)} DESC"


def add_descending_indexes(table: Table) -> None:
    """Declare one table set's descending indexes on its document table.

    Called by :func:`sm_records.models._record.make_record_tables` once the
    table exists, and **not** from :func:`record_args`, which runs while
    ``__table_args__`` is being built and therefore has only column *names* to
    work with. These indexes need the real :class:`~sqlalchemy.Column` objects:
    see :class:`_DescNullsLast` for what an index Alembic cannot find the
    columns of does to every future autogenerate run.

    One index per nullable sortable column, shaped
    ``(type_id, <column> DESC NULLS LAST, id DESC)`` — exactly the ``ORDER BY``
    ``index/_sorting`` emits for a single descending sort on such a column.
    ``nulls_last`` because the mapper says the column is nullable, and
    ``id DESC`` because ``tiebreak_desc`` reverses the tiebreaker for an
    index-served descending term.

    The ascending indexes in :func:`record_args` cannot answer that ordering on
    **Postgres**, and the reason is not the planner being coy: a btree stores
    one ordering, and reading an ``ASC NULLS LAST`` index backwards yields
    ``DESC NULLS FIRST``. The requested order is neither, so the index was
    ignored and 9,000 rows were sorted to return 25 — on ``-updated_at``, what
    the admin list sorts by when a reader clicks the column, and on
    ``-published_at``, what a content listing sorts by (S2).

    ``position``, ``created_at`` and ``display_title`` are ``NOT NULL``, so
    their sorts drop ``NULLS LAST`` (``index._fixed``) and the ascending index
    read backwards already *is* their order. They get no second index, which is
    why :data:`DESCENDING_SORT_COLUMNS` is the nullable three and not all six.
    """
    names = descending_index_names(table.name)
    for name, source in zip(names, DESCENDING_SORT_COLUMNS, strict=True):
        Index(name, table.c.type_id, _DescNullsLast(table.c[source]), table.c.id.desc())


def record_args(table: str, slug_index: str, group_locale_index: str, uuid_index: str) -> tuple:
    """``__table_args__`` for one table set's document table."""
    return (
        # Tenancy design §B/§C. The type's foreign key spans the tenant, so a
        # record can never belong to a different tenant from its type, and
        # every ``type_id``-led index and unique below is per-tenant by
        # construction. Unnamed on purpose: the naming convention keys on
        # ``column_0`` and so keeps the single-column key's name,
        # ``fk_<table>_type_id_records_type`` — hash-truncated past 63 bytes
        # for a long collection name, which is why the migration reads the
        # name off this constraint rather than spelling it.
        ForeignKeyConstraint(
            ["type_id", "tenant_id"],
            [f"{TYPE_TABLE}.id", f"{TYPE_TABLE}.tenant_id"],
            ondelete="RESTRICT",
        ),
        # The uuid is unique per tenant, not per install: an export from one
        # tenant imported into another keeps its uuids (§C).
        Index(uuid_index, "tenant_id", "uuid", unique=True),
        Index(f"ix_{table}_type_status_position", "type_id", "status", "position"),
        # One composite per sortable fixed column, all shaped
        # ``(type_id, <column>, id)``. A list page is always narrowed to one
        # type and always ends its ``ORDER BY`` with ``Record.id`` (the
        # tiebreaker that makes a page boundary deterministic and a cursor
        # unambiguous), so this is the exact key the order needs: SQLite and
        # Postgres can both walk it and stop after ``page_size`` rows instead
        # of sorting the whole type into a temp B-tree.
        #
        # Two things have to stay true for them to be used, and both are in
        # ``index/_sorting.py``: the ordering must not wear ``NULLS LAST`` on
        # a column the database knows is ``NOT NULL`` (it is not the order a
        # btree stores), and the tiebreaker must be ``id`` and nothing else.
        #
        # ``display_title`` earns its own for a second reason: it is what the
        # relation picker searches, and a prefix match over a covering index
        # is the difference between reading three columns of an index and
        # reading every row of the type.
        #
        # They are not free — six more btree inserts per record written. That
        # is the trade §7.3 already makes for every indexed field, made once
        # more for the projection every record has. Three of them are joined by
        # a *descending* twin declared in :func:`add_descending_indexes`, which
        # has to wait until the columns exist — see there for why the nullable
        # ones need a second index at all.
        Index(f"ix_{table}_type_position_id", "type_id", "position", "id"),
        Index(f"ix_{table}_type_published_id", "type_id", "published_at", "id"),
        Index(f"ix_{table}_type_updated_id", "type_id", "updated_at", "id"),
        Index(f"ix_{table}_type_created_id", "type_id", "created_at", "id"),
        Index(f"ix_{table}_type_title_id", "type_id", "display_title", "id"),
        Index(f"ix_{table}_type_slug_id", "type_id", "slug", "id"),
        # Partial unique: a slug is unique within its type **and its locale**,
        # among rows that have one. ``locale`` is in the key rather than beside
        # it because the alternative — a locale column whose slugs are still
        # globally unique per type — is precisely the half-version the original
        # design warned about, the one where ``?locale=de`` starts serving the
        # English record (Phase 5 §4.1). The index is on the row, not on live
        # rows — a soft-deleted record keeps its slug claimed, as pagebuilder
        # does for trashed pages, so a restore can never find its address taken.
        #
        # Alembic autogenerate does not compare an index's ``WHERE``: it sees
        # the name and the columns and reports no change. So if this predicate
        # is edited — or the deployed index was created without one — nothing
        # will tell you. ``SM010``/``SM011`` are about revisions and tables and
        # are equally blind to it. Changing the predicate therefore means
        # hand-writing the drop-and-recreate into a revision, and verifying the
        # deployed definition (``\di+`` / ``sqlite_master``) rather than
        # trusting a clean autogenerate.
        Index(
            slug_index,
            "type_id",
            "locale",
            "slug",
            unique=True,
            postgresql_where=text("slug IS NOT NULL"),
            sqlite_where=text("slug IS NOT NULL"),
        ),
        # One record per language per translation group (Phase 5 §4.3). A
        # second "add German" — a double submit, a stale tab, two rows of an
        # import sharing a group — otherwise produces two German siblings and
        # every language switcher starts contradicting itself. Trashed rows are
        # included, deliberately: a sibling in the trash still claims its slug
        # in its locale, so the language is occupied until it is purged.
        #
        # ``type_id`` **leads the key**. §4.3 states the rule as "one record
        # per ``(translation_group, locale)``" and every reader of a group
        # (``list_translations``, ``_sibling``, ``published_siblings``) scopes
        # by type, so an index without it was wider than the concept it
        # enforces: an import into type B naming a group that exists in type A
        # was refused with "a B record in 'en' already exists in that
        # translation group" — a refusal naming a record that does not exist.
        Index(group_locale_index, "type_id", "translation_group", "locale", unique=True),
    )
