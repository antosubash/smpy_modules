"""Everything a record write does to its payload before the row is touched.

Validation, the size ceiling, the denormalised ``display_title`` and ``slug``,
and the two application-enforced uniqueness rules — the field one of §7.8 and
the slug one of §5. Kept out of :mod:`sm_records.services.records` so that
module reads as the lifecycle it is rather than as a wall of checks.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.constants import MAX_DISPLAY_TITLE_LEN, MAX_SLUG_LEN, ORPHANED_KEY
from sm_records.index.query import Filter, FilterOp, QueryError, count_query
from sm_records.models import Record, RecordType
from sm_records.schema.compile import (
    PayloadValidationError,
    from_stored,
    get_model,
    to_jsonable,
)
from sm_records.schema.compile import validate_payload as _validate_payload
from sm_records.schema.fields import FieldDefinition, FieldSchemaError, validate_fields
from sm_records.services.errors import Conflict, ValidationFailed

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def field_defs(rtype: RecordType) -> list[FieldDefinition]:
    """The type's stored ``fields``, re-validated into definition objects.

    Re-validating what was validated on save looks redundant and is not: the
    column is plain JSON, a host can edit it with ``psql``, and a definition
    that no longer parses must fail the write loudly rather than silently
    dropping a field from the compiled model.
    """
    try:
        return validate_fields(list(rtype.fields or []))
    except FieldSchemaError as exc:
        raise ValidationFailed(
            f"type {rtype.key!r} has an invalid field definition: {exc}",
            [{"field": exc.key or "__root__", "message": exc.problem}],
        ) from exc


def validate(
    rtype: RecordType,
    defs: list[FieldDefinition],
    data: dict[str, Any],
    *,
    max_payload_bytes: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate one write payload. Returns ``(python values, stored values)``.

    Both, because they are genuinely different things: the caller computes a
    ``display_title`` and checks ``unique`` against real ``Decimal`` and
    ``date`` objects, and the JSON column stores their serialised form — the
    split :func:`~sm_records.schema.compile.to_jsonable` exists for.

    ``get_model`` is keyed on ``(key, schema_version)`` and never on the key
    alone, so a schema edit cannot leave an old validator serving writes.

    ``_orphaned`` is refused outright. Design §8.2 makes it the destructive
    schema path's own storage — the keys of deleted fields, kept so a
    mis-clicked field deletion is undoable — which means an inbound payload
    has two ways to ruin it and no way to improve it: inventing content nobody
    ever wrote, or (far likelier) omitting the key on an ordinary edit and
    erasing the recovery data for every field the type has ever dropped.
    :func:`~sm_records.services.records.update_record` carries the stored
    value forward instead.
    """
    if ORPHANED_KEY in data:
        raise ValidationFailed(
            f"{ORPHANED_KEY!r} is reserved and cannot be written directly",
            [{"field": ORPHANED_KEY, "message": f"{ORPHANED_KEY!r} is a reserved key"}],
        )
    model = get_model(rtype.key, rtype.schema_version, defs, type_id=rtype.id)
    try:
        values = _validate_payload(model, data)
    except PayloadValidationError as exc:
        raise ValidationFailed(str(exc), exc.errors) from exc
    stored = to_jsonable(values)
    size = len(json.dumps(stored, default=str).encode("utf-8"))
    if size > max_payload_bytes:
        raise ValidationFailed(
            f"payload is {size} bytes, over the {max_payload_bytes}-byte limit",
            [{"field": "__root__", "message": f"payload exceeds {max_payload_bytes} bytes"}],
        )
    return values, stored


def display_title(rtype: RecordType, values: dict[str, Any]) -> str:
    """Design §5: denormalised so the list screen never parses JSON."""
    if not rtype.display_field:
        return ""
    value = values.get(rtype.display_field)
    return "" if value is None else str(value)[:MAX_DISPLAY_TITLE_LEN]


def slugify(value: str) -> str:
    """Minimal and local on purpose — ``news.slugify`` belongs to ``news``,
    and a published module that imported it would depend on a sibling
    distribution for eight characters of regex."""
    return _SLUG_RE.sub("-", value.lower()).strip("-")[:MAX_SLUG_LEN].strip("-") or ""


def slug_for(rtype: RecordType, values: dict[str, Any], slug: str | None) -> str | None:
    """An explicit slug wins; otherwise derive one from ``slug_field``."""
    if slug is not None:
        return slugify(slug) or None
    if not rtype.slug_field:
        return None
    value = values.get(rtype.slug_field)
    return (slugify(str(value)) or None) if value is not None else None


async def ensure_slug_free(
    db: AsyncSession, rtype: RecordType, slug: str | None, *, exclude_id: int | None = None
) -> None:
    """A slug is unique within its type, **including the trash** (design §5).

    ``include_deleted`` is the whole point: a slug that frees on delete is a
    slug that can be taken while the original sits restorable, and the restore
    then fails or silently renames. The partial unique index would catch this
    at the DB anyway — checking here turns an ``IntegrityError`` at flush into
    a 409 that names the field.
    """
    if slug is None:
        return
    stmt = select(Record.id).where(Record.type_id == rtype.id, Record.slug == slug)
    if exclude_id is not None:
        stmt = stmt.where(Record.id != exclude_id)
    taken = (await db.execute(stmt.execution_options(include_deleted=True))).scalars().first()
    if taken is not None:
        raise Conflict(f"slug {slug!r} is already used by another {rtype.key} record")


async def ensure_unique(
    db: AsyncSession,
    rtype: RecordType,
    defs: list[FieldDefinition],
    values: dict[str, Any],
    *,
    exclude_id: int | None = None,
) -> None:
    """Design §7.8: ``unique`` is application-enforced, against the index.

    The ``(type_id, field_key, value)`` index cannot carry a unique constraint
    — every field of a kind shares the table and the keys are chosen at
    runtime — so this is a ``SELECT`` before the write, inside the request's
    transaction, serialised per type by :func:`lock_type`.

    ``count_query`` rather than a hand-written select, so the truncation
    re-check of §7.4 (``value`` *and* ``value_full``) is the same code a
    filter uses. ``include_deleted`` for the same reason as the slug: index
    rows survive a soft delete (§7.3) and the trash keeps its claims, so a
    trashed record still owns its unique value until it is purged.

    **The statement is built inside the ``try``**, because that is where the
    failure is: ``count_query`` refuses a field with a ``reindex_pending``
    marker (§8.5) while it is being *built*, not when it runs. Built outside,
    the ``QueryError`` escaped as the query grammar's own 400/409 about a
    filter the caller never wrote — and this branch, which says the true
    thing (the write cannot be checked, so it is refused), was unreachable.
    A ``QueryError`` for any other reason is re-raised untouched: a ``unique``
    field that is somehow not indexed is a broken definition, not a rebuild.
    """
    for field in defs:
        if not field.unique:
            continue
        value = values.get(field.key)
        if value is None:
            continue
        try:
            stmt = count_query(
                rtype, list(rtype.fields or []), [Filter(field.key, FilterOp.EQ, value)]
            )
            if exclude_id is not None:
                stmt = stmt.where(Record.id != exclude_id)
            taken = (await db.execute(stmt.execution_options(include_deleted=True))).scalar_one()
        except QueryError as exc:
            if exc.reason != "reindexing":
                raise
            raise Conflict(
                f"{field.key!r} is being reindexed, so its uniqueness cannot be checked; "
                "writes to this type are refused until the rebuild completes"
            ) from exc
        if taken:
            raise Conflict(f"{field.key!r} must be unique; {value!r} is already taken")


async def lock_type(db: AsyncSession, rtype: RecordType) -> None:
    """Serialise writes of one type — the mitigation design §7.8 names.

    The ``unique`` check is check-then-act, so two concurrent creates carrying
    the same value can both pass it. Taking the type row ``FOR UPDATE`` first
    makes the window empty: the second writer waits for the first to commit
    and then sees its index row. On SQLite this compiles to nothing, because
    the database is single-writer anyway; on Postgres it is the row lock.
    """
    await db.execute(select(RecordType.id).where(RecordType.id == rtype.id).with_for_update())


def read_view(
    rtype: RecordType,
    record: Record,
    *,
    with_invalid: bool = True,
    defs: list[FieldDefinition] | None = None,
) -> dict[str, Any]:
    """The lenient read of §8.3: what this row looks like under the *current*
    schema, whether it is behind it, and what about it no longer validates.

    ``data`` is nested rather than merged with ``schema_stale`` because a
    field key may legally *be* ``schema_stale`` — ``TYPE_KEY_PATTERN`` allows
    it — and a payload key silently overwriting a status flag is the kind of
    collision that is only ever found in production.

    ``invalid`` is the "marked, not hidden" badge §8.3 insists on. A record
    that stops satisfying the schema — because a constraint was tightened,
    a field became required, or a type change will not coerce for this value —
    is still returned, still editable and still readable; it simply says which
    fields are wrong. Hiding it is what makes people stop trusting the module,
    and a third ``status`` value would make "invalid" a state someone can set.

    ``with_invalid=False`` is what a *list* passes, and it is the difference
    between one validation and fifty: the coercing read stays (a list screen
    shows values, and they have to read under the current schema), but nothing
    is validated and ``invalid`` comes back empty. A badge per row would cost a
    full pydantic pass per record on every page of every list, and the place
    that acts on ``invalid`` — the editor — opens one record at a time.

    ``defs`` lets a caller with many records of one type validate the type's
    field definitions once instead of per row; it must be ``field_defs(rtype)``
    for this exact type, and is computed here when it is not supplied.
    """
    defs = field_defs(rtype) if defs is None else defs
    view = from_stored(defs, dict(record.data or {}))
    invalid: list[dict[str, str]] = []
    if with_invalid:
        model = get_model(rtype.key, rtype.schema_version, defs, type_id=rtype.id)
        try:
            _validate_payload(model, view)
        except PayloadValidationError as exc:
            invalid = exc.errors
    return {
        "data": view,
        "schema_stale": record.schema_version != rtype.schema_version,
        "invalid": invalid,
    }
