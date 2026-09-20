"""Finding the record an incoming row is about.

Split from :mod:`sm_records.services._import_rows` for the 300-line cap, along
the seam that was already there: that module owns what happens *to* one row —
the envelope it carries, whether it changes anything, how it is written — and
this one owns the single question that has to be answered for the whole file at
once, in as few statements as possible.

**Batched, never per row.** One lookup per row turned a 40k-row file into 40k
round trips before anything was written.

**Every slug lookup takes a locale** (Phase 5 §4.3). A slug is unique per
``(type, locale)``, so matching on the slug alone would pick whichever
language's record came back first — an import of the German file quietly
rewriting the English records.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.index.query import Filter, FilterOp, build_query
from sm_records.models import Record, RecordType
from sm_records.schema.fields import FieldDefinition
from sm_records.services._import_parse import ImportRow
from sm_records.services._import_rows import envelope_for
from sm_records.services.errors import ValidationFailed

__all__ = ["MATCH_SLUG", "MATCH_UUID", "match_field", "resolve_matches"]

MATCH_UUID = "uuid"
MATCH_SLUG = "slug"

_CHUNK = 500
"""How many identifiers go into one ``IN`` lookup. Bounded because SQLite
refuses a statement with more than 999 bound parameters by default, and a
40k-row file would otherwise be one statement nobody can execute."""


def match_field(rtype: RecordType, defs: list[FieldDefinition], match_by: str) -> FieldDefinition:
    """``match_by`` naming a field: it has to be a ``unique`` one.

    Matching on a non-unique field is not a stricter version of the same
    feature — it is an import that updates an arbitrary one of the records
    that share the value, chosen by whatever order the index happens to
    return. Refusing it is the only answer that does not corrupt data quietly.
    """
    for field in defs:
        if field.key == match_by:
            if not field.unique:
                raise ValidationFailed(
                    f"match_by={match_by!r} is not a unique field of {rtype.key!r}",
                    [{"field": "match_by", "message": f"{match_by!r} is not unique"}],
                )
            return field
    raise ValidationFailed(
        f"match_by must be 'uuid', 'slug' or a unique field of {rtype.key!r}, not {match_by!r}",
        [{"field": "match_by", "message": f"{match_by!r} is not a field of {rtype.key!r}"}],
    )


async def resolve_matches(
    db: AsyncSession,
    rtype: RecordType,
    rows: Sequence[ImportRow],
    *,
    match_by: str,
    defs: list[FieldDefinition],
) -> dict[int, Record]:
    """``{row number: matched record}`` for the whole file.

    Batched: one lookup per row turned a 40k-row file into 40k round trips
    before anything was written. ``include_deleted`` because a trashed record
    still owns its ``uuid`` and its slug (§5, §7.3) — an import that could not
    see it would try to *create* a duplicate and be refused by the unique
    index with a message naming nothing the operator can see.
    """
    if match_by == MATCH_UUID:
        # Unscoped: ``uuid`` is unique across the whole install, so a file
        # naming one that belongs to *another* type must be reported as that
        # rather than pass the lookup and fail at the unique index as a 500.
        # ``import_`` checks ``type_id`` on what comes back.
        return await _by_column(db, rtype, rows, Record.uuid, lambda row: row.uuid, scoped=False)
    if match_by == MATCH_SLUG:
        return await _by_slug(db, rtype, rows)
    field = match_field(rtype, defs, match_by)
    out: dict[int, Record] = {}
    fields = list(rtype.fields or [])
    for row in rows:
        value = (row.values or {}).get(field.key)
        if value is None:
            continue
        stmt = build_query(rtype, fields, [Filter(field.key, FilterOp.EQ, value)]).limit(1)
        found = (await db.execute(stmt.execution_options(include_deleted=True))).scalars().first()
        if found is not None:
            out[row.number] = found
    return out


async def _by_slug(
    db: AsyncSession, rtype: RecordType, rows: Sequence[ImportRow]
) -> dict[int, Record]:
    """``match_by=slug``, scoped to each row's locale (Phase 5 §4.3).

    A slug is unique per ``(type, locale)`` and no longer per type, so a lookup
    that matched on the slug alone would pick whichever language's record the
    database happened to return first — an import of the German file quietly
    rewriting the English records. ``row.locale`` is the resolved content
    locale ``import_._validate`` put there; a row that never reached validation
    is not in ``rows``.
    """
    wanted: dict[int, tuple[str, str]] = {}
    for row in rows:
        slug = envelope_for(row).slug or None
        if slug and row.locale:
            wanted[row.number] = (row.locale, slug)
    slugs = sorted({slug for _, slug in wanted.values()})
    found: dict[tuple[str, str], Record] = {}
    for start in range(0, len(slugs), _CHUNK):
        stmt = select(Record).where(
            Record.type_id == rtype.id, Record.slug.in_(slugs[start : start + _CHUNK])
        )
        matches = (await db.execute(stmt.execution_options(include_deleted=True))).scalars().all()
        for record in matches:
            found[(record.locale, str(record.slug))] = record
    return {number: found[key] for number, key in wanted.items() if key in found}


async def _by_column(
    db: AsyncSession,
    rtype: RecordType,
    rows: Sequence[ImportRow],
    column: Any,
    key_of: Any,
    *,
    scoped: bool = True,
) -> dict[int, Record]:
    wanted = {row.number: key_of(row) for row in rows}
    keys = sorted({value for value in wanted.values() if value})
    found: dict[str, Record] = {}
    for start in range(0, len(keys), _CHUNK):
        chunk = keys[start : start + _CHUNK]
        stmt = select(Record).where(column.in_(chunk))
        if scoped:
            stmt = stmt.where(Record.type_id == rtype.id)
        rows_found = (
            (await db.execute(stmt.execution_options(include_deleted=True))).scalars().all()
        )
        for record in rows_found:
            found[str(getattr(record, column.key))] = record
    return {number: found[value] for number, value in wanted.items() if value in found}
