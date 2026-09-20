"""The document table's indexes — every one of them, named after its table.

Split out of :mod:`sm_records.models._record` for the 300-line cap, along the
seam the factory already drew: that module declares the *columns* a record
has, and this one declares what the database is asked to keep sorted about
them. Both are called once per table set (Phase 5 §6), so a collection's
document table carries exactly these indexes under exactly these names with
its own prefix — which is what ``tests/test_collections_ddl.py`` compares.

The names are derived from the table rather than written out because two of
them are read back by name elsewhere (:class:`~sm_records.models._record.RecordTables`)
and because index names are schema-global on Postgres:
``ix_records_record_type_slug`` can exist exactly once, so a collection's copy
has to be spelled from its own prefix or the second ``CREATE INDEX`` fails.
"""

from __future__ import annotations

from sqlalchemy import Index, text

__all__ = ["record_args"]


def record_args(table: str, slug_index: str, group_locale_index: str) -> tuple:
    """``__table_args__`` for one table set's document table."""
    return (
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
        # more for the projection every record has.
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
        Index(group_locale_index, "translation_group", "locale", unique=True),
    )
