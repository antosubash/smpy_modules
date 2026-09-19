"""HTTP-facing DTOs for the Records API and admin views.

SQLModel throughout, per ``CLAUDE.md`` — never a plain pydantic ``BaseModel``.
The read shapes (``TypeRead``, ``RecordRead``, ``RevisionRead``) are built by
:func:`type_read` / :func:`record_read` / :func:`revision_read` rather than
constructed ad hoc at each call site, so the API and the Inertia views render
one serialisation of a row rather than two that can drift.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from sm_records.models import Record, RecordRevision, RecordType
from sm_records.services.records import read_view

__all__ = [
    "RecordCreate",
    "RecordPage",
    "RecordRead",
    "RecordUpdate",
    "RevisionListResponse",
    "RevisionRead",
    "TypeCreate",
    "TypeListResponse",
    "TypeRead",
    "TypeUpdate",
    "record_read",
    "revision_read",
    "type_read",
]


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
    allowed_roles: list[str]
    record_count: int
    fields_locked: bool
    """``record_count > 0`` — design §16's Phase 1 rule: a type's ``fields``
    are read-only once it holds a record. Carried here so the UI can disable
    the field editor without a second request."""
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
    allowed_roles: list[str] = SQLField(default_factory=list)


class TypeUpdate(SQLModel):
    """Every field but ``expected_version`` is optional; only the ones the
    caller actually sent should reach ``update_type`` — see
    ``endpoints/api/types.py``'s ``model_dump(exclude_unset=True)``."""

    expected_version: int
    label: str | None = None
    label_plural: str | None = None
    description: str | None = None
    icon: str | None = None
    fields: list[dict[str, Any]] | None = None
    display_field: str | None = None
    slug_field: str | None = None
    is_public: bool | None = None
    allowed_roles: list[str] | None = None


class RecordRead(SQLModel):
    uuid: str
    type_key: str
    data: dict[str, Any]
    schema_stale: bool
    version: int
    schema_version: int
    status: str
    slug: str | None
    display_title: str
    position: int
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime | None
    is_deleted: bool


class RecordPage(SQLModel):
    items: list[RecordRead]
    total: int
    page: int
    page_size: int


class RecordCreate(SQLModel):
    data: dict[str, Any] = SQLField(default_factory=dict)
    status: str | None = None
    slug: str | None = None
    position: int = 0


class RecordUpdate(SQLModel):
    expected_version: int
    data: dict[str, Any]
    status: str | None = None
    slug: str | None = None
    position: int | None = None


class RevisionRead(SQLModel):
    id: int
    version: int
    schema_version: int
    event: str
    display_title: str
    created_at: datetime
    created_by: str | None


class RevisionListResponse(SQLModel):
    items: list[RevisionRead]


def type_read(rtype: RecordType, record_count: int) -> TypeRead:
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
        allowed_roles=list(rtype.allowed_roles or []),
        record_count=record_count,
        fields_locked=record_count > 0,
        created_at=rtype.created_at,
        updated_at=rtype.updated_at,
    )


def record_read(rtype: RecordType, record: Record) -> RecordRead:
    """The one lenient read every caller gets: ``read_view`` fills a missing
    key from ``default`` and flags a row stamped at an old schema version
    rather than failing it (design §8.3)."""
    view = read_view(rtype, record)
    return RecordRead(
        uuid=record.uuid,
        type_key=rtype.key,
        data=view["data"],
        schema_stale=view["schema_stale"],
        version=record.version,
        schema_version=record.schema_version,
        status=record.status.value,
        slug=record.slug,
        display_title=record.display_title,
        position=record.position,
        published_at=record.published_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        is_deleted=record.is_deleted,
    )


def revision_read(revision: RecordRevision) -> RevisionRead:
    return RevisionRead(
        id=revision.id,
        version=revision.version,
        schema_version=revision.schema_version,
        event=revision.event.value,
        display_title=revision.display_title,
        created_at=revision.created_at,
        created_by=revision.created_by,
    )
