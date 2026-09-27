"""Validating a proposed schema, and snapshotting the one that was accepted.

Split from :mod:`sm_records.services.types` for the file cap. The grouping is
real, though: everything here answers "may this ``fields`` list be stored?",
which is the question design §6 and §8 are about, while ``types`` owns the row
lifecycle around it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records._text import NUL_PROBLEM, has_nul
from sm_records.models import RecordType, RecordTypeRevision
from sm_records.schema.fields import FieldDefinition, FieldSchemaError, validate_fields
from sm_records.schema.types import FieldType
from sm_records.services._common import type_id_map, utcnow
from sm_records.services.errors import ValidationFailed
from sm_records.settings import RecordsSettings

_TEXT_COLUMNS = ("label", "label_plural", "description", "icon")
"""The type row's free-text columns. ``key`` is absent because it is matched
against ``TYPE_KEY_PATTERN`` and ``collection`` because it is matched against
the declared set."""


def check_type_text(values: dict[str, Any]) -> None:
    """Refuse a NUL in anything about a type that is stored as text.

    Called by both write paths — ``create_type`` and ``update_type`` — over
    whatever each of them is about to set, so a column absent from the call is
    not examined and a column present is. A type's labels are written to a
    ``varchar`` and its ``allowed_roles`` to a JSON column, and Postgres
    refuses ``\x00`` in both from the driver: a 500 for a value that is simply
    not storable, where the rest of this module answers 422 and names the
    field.
    """
    for name in _TEXT_COLUMNS:
        if has_nul(values.get(name)):
            raise ValidationFailed(
                f"{name} {NUL_PROBLEM}", [{"field": name, "message": NUL_PROBLEM}]
            )
    for role in values.get("allowed_roles") or []:
        if has_nul(role):
            raise ValidationFailed(
                f"allowed_roles {NUL_PROBLEM}",
                [{"field": "allowed_roles", "message": NUL_PROBLEM}],
            )


def normalise(fields_raw: list[dict[str, Any]], settings: RecordsSettings):
    """Validate a proposed field list and return ``(definitions, stored form)``.

    The stored form is the *normalised* dump rather than what the caller sent:
    the validator fills defaults (``on_delete``, ``many``) and promotes
    ``unique`` to ``indexed``, and storing the raw input would make the next
    edit's "did the fields change?" comparison answer yes to a no-op.
    """
    try:
        # ``on_save``: this is the one path a proposed schema takes (type
        # create, update, rollback and the preview of any of them), and the
        # only one where a field key colliding with a registered index
        # provider's virtual key may be refused — refusing it on a *load*
        # takes an already-stored type offline. See ``schema._keys``.
        defs = validate_fields(list(fields_raw or []), on_save=True)
    except FieldSchemaError as exc:
        raise ValidationFailed(
            str(exc), [{"field": exc.key or "__root__", "message": exc.problem}]
        ) from exc
    if len(defs) > settings.max_fields_per_type:
        raise ValidationFailed(
            f"{len(defs)} fields exceeds the limit of {settings.max_fields_per_type}"
        )
    indexed = sum(1 for field in defs if field.indexed)
    if indexed > settings.max_indexed_fields_per_type:
        raise ValidationFailed(
            f"{indexed} indexed fields exceeds the limit of "
            f"{settings.max_indexed_fields_per_type}; every indexed field is a row "
            "written per record per save"
        )
    return defs, [field.model_dump(mode="json") for field in defs]


DISPLAY_FIELD_TYPES: frozenset[FieldType] = frozenset(
    {
        FieldType.TEXT,
        FieldType.SELECT,
        FieldType.EMAIL,
        FieldType.URL,
        FieldType.INTEGER,
        FieldType.NUMBER,
        FieldType.DATE,
        FieldType.DATETIME,
    }
)
"""What ``display_field`` may point at: the types ``_payload.display_title``
can ``str()`` into something a person reads in a list column. ``json`` and
``media`` stringify to ``str(dict)`` truncated at 300 characters,
``multiselect`` to a Python list literal, ``relation`` to ``{'type': ...}``,
``boolean`` to ``True``/``False`` and ``longtext`` to a paragraph — all
accepted silently before, all useless as a title."""

SLUG_FIELD_TYPES: frozenset[FieldType] = frozenset(
    {FieldType.TEXT, FieldType.SELECT, FieldType.EMAIL, FieldType.URL}
)
"""What ``slug_field`` may point at — narrower than ``display_field``: a slug
is an address, so it has to be per-record distinct free text. A ``boolean``
slug field gives every record the slug ``true`` or ``false`` and the second
write 409s; a date or a number is barely better."""

_POINTER_TYPES: dict[str, frozenset[FieldType]] = {
    "display_field": DISPLAY_FIELD_TYPES,
    "slug_field": SLUG_FIELD_TYPES,
}


def check_pointers(
    defs: list[FieldDefinition], display_field: str | None, slug_field: str | None
) -> None:
    by_key = {field.key: field for field in defs}
    for name, value in (("display_field", display_field), ("slug_field", slug_field)):
        if value is None:
            continue
        field = by_key.get(value)
        if field is None:
            raise ValidationFailed(
                f"{name} {value!r} is not a field of this type",
                [{"field": name, "message": f"{value!r} is not a declared field"}],
            )
        allowed = _POINTER_TYPES[name]
        if field.type not in allowed:
            kinds = sorted(member.value for member in allowed)
            raise ValidationFailed(
                f"{name} cannot point at a {field.type.value} field; it takes one of {kinds}",
                [
                    {
                        "field": name,
                        "message": f"{value!r} is a {field.type.value} field, "
                        f"which cannot be used as {name}",
                    }
                ],
            )


async def check_targets(db: AsyncSession, defs: list[FieldDefinition], self_key: str) -> None:
    """Every ``relation`` must point at a type that exists.

    The one rule ``schema.fields`` cannot enforce — it is pure and this needs a
    query. A self-relation is allowed and is why ``self_key`` is passed rather
    than read from the database: on a create, the type is not there yet.
    """
    known = set(await type_id_map(db)) | {self_key}
    errors = [
        {
            "field": field.key,
            "message": f"target type {field.options.get('target_type')!r} does not exist",
        }
        for field in defs
        if field.type is FieldType.RELATION and field.options.get("target_type") not in known
    ]
    if errors:
        raise ValidationFailed("; ".join(item["message"] for item in errors), errors)


def pointers_moved(rtype: RecordType, changes: dict[str, Any]) -> bool:
    """Does ``changes`` move ``display_field`` or ``slug_field`` off its value?"""
    return any(
        name in changes and changes[name] != getattr(rtype, name)
        for name in ("display_field", "slug_field")
    )


async def write_type_row(
    db: AsyncSession,
    rtype: RecordType,
    *,
    changes: dict[str, Any],
    fields: list[dict[str, Any]] | None,
    expected_version: int,
    actor: str | None,
    take_snapshot: bool,
) -> None:
    """Write an accepted edit onto the type row, after its guarded bump.

    Both type-edit paths end here; each passes its own ``take_snapshot`` rule,
    because they differ on which edits write a ``records_type_revision`` row.
    """
    for name, value in changes.items():
        setattr(rtype, name, value)
    if fields is not None:
        rtype.fields = fields
        rtype.schema_version = rtype.schema_version + 1
    rtype.version = expected_version + 1
    rtype.updated_by = actor
    db.add(rtype)
    await db.flush()
    if take_snapshot:
        await snapshot(db, rtype, actor)


async def snapshot(db: AsyncSession, rtype: RecordType, actor: str | None) -> RecordTypeRevision:
    revision = RecordTypeRevision(
        type_id=rtype.id,
        version=rtype.version,
        schema_version=rtype.schema_version,
        fields=list(rtype.fields or []),
        display_field=rtype.display_field,
        slug_field=rtype.slug_field,
        created_at=utcnow(),
        created_by=actor,
    )
    db.add(revision)
    await db.flush()
    return revision
