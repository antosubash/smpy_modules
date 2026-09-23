"""What one table set's document half exposes to the rest of the module.

Split from :mod:`sm_records.models._record` for the 300-line cap, along the
seam between *declaring* the document and revision tables (that module) and
*describing* them to the two layers that read their names back — the write
path that turns a unique-index refusal into a 409, and the table-set registry.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["RecordTables"]


@dataclass(frozen=True, slots=True)
class RecordTables:
    """One table set's document half, and the index names two layers read back.

    The names travel with the classes rather than sitting at module scope
    because a collection's indexes are named after *its* tables, and the 409
    that :func:`sm_records.services._claims.flush_write` raises is recognised by
    matching the database's own words. A signature left at the global spelling
    would turn every lost slug race inside a collection back into a 500 —
    which is the same failure the global signatures were added to fix.
    """

    record: type
    revision: type
    slug_index: str
    group_locale_index: str
    uuid_signatures: tuple[str, ...]
    """The same two spellings for "that uuid is taken **in this tenant**" — the
    ``(tenant_id, uuid)`` unique index (tenancy design §C). Reached by an import
    that keeps a file's uuid and lost a race for it."""
    slug_signatures: tuple[str, ...]
    """How each backend says "that slug is taken" in an ``IntegrityError``.

    Two spellings because the two dialects report a different thing. Postgres
    names the constraint (``duplicate key value violates unique constraint
    "ix_records_record_type_slug"``); SQLite names the *columns*
    (``UNIQUE constraint failed: records_record.type_id, records_record.locale,
    records_record.slug``) and never mentions the index at all. The column list
    is therefore part of this contract: anything matching neither is re-raised,
    because an ``IntegrityError`` this module cannot explain is a bug rather
    than a 409."""
    group_locale_signatures: tuple[str, ...]
    """The same two spellings for "that language is already taken in this
    group".

    Reached only by a writer that sets ``translation_group`` itself — an import
    carrying the column, or a second ``POST /translations`` that lost the race
    with the first. :func:`sm_records.services._translations.create_translation`
    checks for the sibling first; this is what closes the window behind it, and
    it costs the ordinary write path nothing because the string comparison
    happens only after a flush has already failed."""
