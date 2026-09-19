"""Everything a record write does to its payload before the row is touched.

Validation, the size ceiling, the denormalised ``display_title`` and ``slug``,
the ``_orphaned`` migration of §8.3, and the lenient read of §8.2. Kept out of
:mod:`sm_records.services.records` so that module reads as the lifecycle it is
rather than as a wall of checks.

The two claims a write makes about the *rest of the type* — the ``unique``
rule of §7.8 and the slug rule of §5, plus the lock that makes them hold —
live next door in :mod:`sm_records.services._claims`.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sm_records.constants import MAX_DISPLAY_TITLE_LEN, MAX_SLUG_LEN, ORPHANED_KEY
from sm_records.models import Record, RecordType
from sm_records.schema.compile import (
    PayloadValidationError,
    from_stored,
    get_model,
    to_jsonable,
)
from sm_records.schema.compile import validate_payload as _validate_payload
from sm_records.schema.fields import FieldDefinition, FieldSchemaError, validate_fields
from sm_records.services.errors import ValidationFailed

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


def migrate_orphaned(
    record: Record,
    defs: list[FieldDefinition],
    stored: dict[str, Any],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The lazy destructive migration of §8.3, run on this one record.

    Two moves, both against the *stored* payload and neither ever bulk:

    * a top-level key the current schema no longer declares is a deleted
      field's value. It moves under ``_orphaned`` — which is what makes a
      mis-clicked field deletion undoable, at the cost of some storage, and
      why nothing rewrites the whole type when a field goes (§8.2).
    * a key the schema *does* declare is dropped from ``_orphaned``: the field
      came back and its value is live again. The read path already served it
      from there (``schema.compile.from_stored``), so by now it is in ``stored``
      — either as the value the client sent back or as the field's default.

    ``_orphaned`` itself is never client-supplied (``_payload.validate``
    refuses a payload carrying it), so an update that does not mention it must
    not be read as "delete it": what survives here is carried across.

    ``extra`` is this module's own contribution to that sub-key, and the only
    way anything reaches it besides the record's own payload — see
    ``services.records.update_record``'s ``orphaned_extra``. It wins over what the record
    carried, because the one caller is a revision restore: putting an older
    payload back means putting back *its* value for a key the schema has since
    dropped, not the one a later edit left behind.
    """
    previous = dict(record.data or {})
    declared = {field.key for field in defs}
    orphaned = dict(previous.get(ORPHANED_KEY) or {})
    for key, value in previous.items():
        if key == ORPHANED_KEY or key in declared:
            continue
        orphaned.setdefault(key, value)
    for key, value in (extra or {}).items():
        if key != ORPHANED_KEY and key not in declared:
            orphaned[key] = value
    for key in declared:
        orphaned.pop(key, None)
    return {**stored, ORPHANED_KEY: orphaned} if orphaned else stored


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
