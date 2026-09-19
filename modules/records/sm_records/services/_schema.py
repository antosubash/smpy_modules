"""Validating a proposed schema, and snapshotting the one that was accepted.

Split from :mod:`sm_records.services.types` for the file cap. The grouping is
real, though: everything here answers "may this ``fields`` list be stored?",
which is the question design §6 and §8 are about, while ``types`` owns the row
lifecycle around it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.models import RecordType, RecordTypeRevision
from sm_records.schema.fields import FieldDefinition, FieldSchemaError, validate_fields
from sm_records.schema.types import FieldType
from sm_records.services._common import type_id_map, utcnow
from sm_records.services.errors import ValidationFailed
from sm_records.settings import RecordsSettings


def normalise(fields_raw: list[dict[str, Any]], settings: RecordsSettings):
    """Validate a proposed field list and return ``(definitions, stored form)``.

    The stored form is the *normalised* dump rather than what the caller sent:
    the validator fills defaults (``on_delete``, ``many``) and promotes
    ``unique`` to ``indexed``, and storing the raw input would make the next
    edit's "did the fields change?" comparison answer yes to a no-op.
    """
    try:
        defs = validate_fields(list(fields_raw or []))
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


def check_pointers(
    defs: list[FieldDefinition], display_field: str | None, slug_field: str | None
) -> None:
    keys = {field.key for field in defs}
    for name, value in (("display_field", display_field), ("slug_field", slug_field)):
        if value is not None and value not in keys:
            raise ValidationFailed(
                f"{name} {value!r} is not a field of this type",
                [{"field": name, "message": f"{value!r} is not a declared field"}],
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
