"""Matching an incoming row to a record, and writing it.

Split from :mod:`sm_records.services.import_` for the file cap, along the seam
that was already there: that module owns the *run* (parse, validate
everything, then write in one transaction and report), and this one owns what
happens to **one** row.

Two rules are enforced here rather than there, because both are about a single
row and its counterpart in the database:

* **A row that says nothing new writes nothing.** Re-importing a file you
  exported must converge, not bump ``version`` on every record in the type —
  and "converge" cannot mean "write the same bytes again", because a write
  appends a revision, rewrites six index tables and invalidates every
  optimistic-concurrency token a client is holding. :func:`unchanged` is what
  makes the second run a no-op, and it is also where ``skipped`` in the report
  comes from.
* **An update never last-write-wins.** The export carries no ``version``
  (design §5 says what travels: ``uuid`` and content), so a file that wants to
  *change* a record has to say which version it is changing — or say ``force``
  and mean it. Silently overwriting whatever is there is precisely the failure
  §5.1 added the column to prevent, and a bulk path is the worst place to make
  an exception for it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import ORPHANED_KEY
from sm_records.contracts.io import ImportMode
from sm_records.index.query import Filter, FilterOp, build_query
from sm_records.models import Record, RecordStatus, RecordType
from sm_records.schema.compile import to_jsonable
from sm_records.schema.fields import FieldDefinition
from sm_records.services._import_parse import ImportRow
from sm_records.services._payload import read_view, slug_for
from sm_records.services.errors import ValidationFailed
from sm_records.services.records import create_record, update_record
from sm_records.settings import RecordsSettings

__all__ = ["Envelope", "envelope_for", "match_field", "resolve_matches", "unchanged", "write_row"]

MATCH_UUID = "uuid"
MATCH_SLUG = "slug"

_CHUNK = 500
"""How many identifiers go into one ``IN`` lookup. Bounded because SQLite
refuses a statement with more than 999 bound parameters by default, and a
40k-row file would otherwise be one statement nobody can execute."""


class Envelope:
    """The non-payload half of a row, coerced once. A named object rather
    than a tuple because three of its four members are optional in different
    ways, and a positional unpack is how ``position`` lands in ``status``."""

    __slots__ = ("has_slug", "position", "slug", "status")

    def __init__(
        self, status: RecordStatus | None, slug: str | None, has_slug: bool, position: int | None
    ) -> None:
        self.status = status
        self.slug = slug
        self.has_slug = has_slug
        self.position = position


def envelope_for(row: ImportRow) -> Envelope:
    """Coerce ``status``/``slug``/``position``, or raise the row's error.

    CSV hands every cell over as a string (``position`` arrives as ``"3"``),
    JSON hands it over typed. One coercion for both is the only reason having
    two formats is not two features that drift.
    """
    raw_status = row.envelope.get("status")
    status: RecordStatus | None = None
    if raw_status not in (None, ""):
        try:
            status = RecordStatus(str(raw_status))
        except ValueError as exc:
            raise ValidationFailed(
                f"unknown status {raw_status!r}",
                [{"field": "status", "message": "status must be 'draft' or 'published'"}],
            ) from exc
    raw_position = row.envelope.get("position")
    position: int | None = None
    if raw_position not in (None, ""):
        try:
            position = int(raw_position)
        except (TypeError, ValueError) as exc:
            raise ValidationFailed(
                f"position {raw_position!r} is not a whole number",
                [{"field": "position", "message": "position must be a whole number"}],
            ) from exc
    slug = row.envelope.get("slug")
    return Envelope(status, None if slug is None else str(slug), "slug" in row.envelope, position)


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
        return await _by_column(
            db, rtype, rows, Record.slug, lambda row: envelope_for(row).slug or None
        )
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


def unchanged(
    rtype: RecordType,
    record: Record,
    row: ImportRow,
    envelope: Envelope,
    defs: list[FieldDefinition],
) -> bool:
    """Would writing this row change anything at all?

    Compared through ``read_view`` on both sides, never raw ``data`` against
    raw ``data``: the file carries every declared key (the exporter fills
    defaults, §8.3), a stored payload written before a field was added does
    not, and comparing those two dictionaries directly would call every such
    record "changed" and rewrite the type on every import.

    ``schema_version`` counts as a difference even when the payload matches,
    because a write restamps the row at the type's current version (§8.3) —
    that restamp is the lazy migration, and skipping it would mean an import
    silently declines to do the one thing a re-import of a stale record is
    good for.
    """
    if record.schema_version != rtype.schema_version:
        return False
    current = to_jsonable(read_view(rtype, record, with_invalid=False, defs=defs)["data"])
    current.pop(ORPHANED_KEY, None)
    if current != (row.stored or {}):
        return False
    if envelope.status is not None and envelope.status is not record.status:
        return False
    if envelope.position is not None and envelope.position != record.position:
        return False
    return slug_for(rtype, row.values or {}, envelope.slug) == record.slug


async def write_row(
    db: AsyncSession,
    rtype: RecordType,
    row: ImportRow,
    record: Record | None,
    *,
    mode: ImportMode,
    envelope: Envelope,
    settings: RecordsSettings,
    actor: str | None,
    force: bool,
) -> str:
    """Write one row and say what it did: ``"created"`` or ``"updated"``.

    Through ``create_record``/``update_record`` and never a bulk insert.
    Everything those do is load-bearing for a *file* too, and more so: the
    revision that makes a bad import undoable, the index tables without which
    the imported rows match no filter, the ``unique`` and slug claims a file
    is likelier to violate than a human typing one form, and ``lock_type``.
    """
    if record is None:
        created = await create_record(
            db,
            rtype,
            data=row.data,
            settings=settings,
            status=envelope.status or RecordStatus.DRAFT,
            slug=envelope.slug,
            position=envelope.position or 0,
            actor=actor,
        )
        if row.uuid:
            # The file's own identity, kept: a round trip that renumbered
            # every record would break every relation pointing into it (§9)
            # and make a second import create duplicates instead of matching.
            created.uuid = row.uuid
            db.add(created)
            await db.flush()
        return "created"

    expected = row.version
    if expected is None:
        if not force:
            raise ValidationFailed(
                f"record {record.uuid} already exists and the file carries no 'version'; "
                "re-export it, add a version column, or import with force=true",
                [{"field": "version", "message": "a version is required to update a record"}],
            )
        expected = record.version
    await update_record(
        db,
        rtype,
        record,
        expected_version=expected,
        data=row.data,
        settings=settings,
        status=envelope.status,
        slug=envelope.slug if envelope.has_slug else None,
        position=envelope.position,
        actor=actor,
    )
    return "updated"


def mode_error(mode: ImportMode, record: Record | None) -> str | None:
    """What ``mode`` forbids about this row, if anything."""
    if mode is ImportMode.CREATE and record is not None:
        return "a record already matches this row, and mode=create never updates"
    if mode is ImportMode.UPDATE and record is None:
        return "no record matches this row, and mode=update never creates"
    return None
