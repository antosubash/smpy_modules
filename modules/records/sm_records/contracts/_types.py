"""HTTP-facing DTOs for a Record **Type** — the schema half of the contract.

Split from :mod:`sm_records.contracts.schemas` for the 300-line cap, along the
seam the JSON API already has between ``endpoints/api/types.py`` and
``endpoints/api/records.py``: this module is "what does a schema look like on
the wire", that one is "what does a document stored against it look like".
Re-exported from ``contracts.schemas``, so every endpoint still imports one
module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from sm_records.index.reindex import pending_map
from sm_records.models import RecordType

__all__ = ["TypeCreate", "TypeListResponse", "TypeRead", "TypeUpdate", "type_read"]


class TypeRead(SQLModel):
    key: str
    label: str
    label_plural: str
    description: str | None
    icon: str | None
    fields: list[dict[str, Any]]
    schema_version: int
    version: int
    display_field: str | None
    slug_field: str | None
    is_public: bool
    translatable: bool
    """Whether this type's records may be authored in more than one content
    locale (Phase 5 §4.1). ``false`` is what keeps the language UI off and the
    create path refusing any locale but the default."""
    allowed_roles: list[str]
    record_count: int
    """Live records only — the number a list screen shows."""
    trashed_record_count: int
    """Records in the trash. Separate from ``record_count`` because the two
    answer different questions: what the type shows, and what deleting it
    would destroy. ``DELETE /types/{key}`` confirms against the *sum*."""
    reindex_pending: dict[str, str]
    """Field key (or ``"*"`` for the whole type) -> ISO enqueue time — a
    schema-affecting change that hasn't finished its out-of-request rebuild
    yet (design §8.5/§8.9). Mirrors ``RecordType.reindex_pending`` exactly;
    the UI reads it to grey out a field as a filter/sort target and to offer
    the manual "Reindex" button."""
    created_at: datetime
    updated_at: datetime | None


class TypeListResponse(SQLModel):
    items: list[TypeRead]


class TypeCreate(SQLModel):
    key: str
    label: str
    label_plural: str | None = None
    description: str | None = None
    icon: str | None = None
    fields: list[dict[str, Any]] = SQLField(default_factory=list)
    display_field: str | None = None
    slug_field: str | None = None
    is_public: bool = False
    translatable: bool = False
    allowed_roles: list[str] = SQLField(default_factory=list)


class TypeUpdate(SQLModel):
    """Every field but ``expected_version`` is optional; only the ones the
    caller actually sent should reach ``update_type`` — see
    ``endpoints/api/types.py``'s ``model_dump(exclude_unset=True)``.

    ``force``/``orphaned`` are not columns and never reach ``**changes`` — they
    are the two retries a 409 from :mod:`sm_records.services.schema_change`
    asks for (§8.2, §8.8), read separately by the endpoint and passed to
    ``update_type`` as their own keyword arguments.
    """

    expected_version: int
    #: Declared only so a body carrying one is refused, not dropped — see
    key: str | None = None  # ``endpoints/api/types.py``'s ``update_type``.
    label: str | None = None
    label_plural: str | None = None
    description: str | None = None
    icon: str | None = None
    fields: list[dict[str, Any]] | None = None
    display_field: str | None = None
    slug_field: str | None = None
    is_public: bool | None = None
    translatable: bool | None = None
    allowed_roles: list[str] | None = None
    force: bool = False
    orphaned: str | None = None


def type_read(rtype: RecordType, record_count: int, trashed_record_count: int) -> TypeRead:
    """Both counts are required rather than defaulted: a caller that forgot
    the trashed one would silently report a populated type as editable."""
    return TypeRead(
        key=rtype.key,
        label=rtype.label,
        label_plural=rtype.label_plural,
        description=rtype.description,
        icon=rtype.icon,
        fields=list(rtype.fields or []),
        schema_version=rtype.schema_version,
        version=rtype.version,
        display_field=rtype.display_field,
        slug_field=rtype.slug_field,
        is_public=rtype.is_public,
        translatable=rtype.translatable,
        allowed_roles=list(rtype.allowed_roles or []),
        record_count=record_count,
        trashed_record_count=trashed_record_count,
        reindex_pending=pending_map(rtype),
        created_at=rtype.created_at,
        updated_at=rtype.updated_at,
    )
