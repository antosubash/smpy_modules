"""HTTP-facing DTOs for the Records API and admin views — Record Type and
Record CRUD.

SQLModel throughout, per ``CLAUDE.md`` — never a plain pydantic ``BaseModel``.
The read shapes (``TypeRead``, ``RecordRead``, ``RevisionRead``) are built by
:func:`type_read` / :func:`record_read` / :func:`revision_read` rather than
constructed ad hoc at each call site, so the API and the Inertia views render
one serialisation of a row rather than two that can drift.

The schema-change half of the contract — the dry-run report, a preview's
response, and the two revision-listing shapes — lives in
``contracts/schema_change.py``, split out for the 300-line cap. The seam is
real: everything here is "what does one row look like on the wire", and that
module is "what does a proposed change to one look like".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from sm_records.index.reindex import pending_map
from sm_records.models import Record, RecordRevision, RecordType
from sm_records.services.records import read_view

__all__ = [
    "RecordCreate",
    "RecordPage",
    "RecordRead",
    "RecordRevisionDetailRead",
    "RecordRevisionRestoreRequest",
    "RecordUpdate",
    "RevisionListResponse",
    "RevisionRead",
    "TypeCreate",
    "TypeListResponse",
    "TypeRead",
    "TypeUpdate",
    "record_read",
    "record_revision_detail_read",
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
    allowed_roles: list[str] = SQLField(default_factory=list)


class TypeUpdate(SQLModel):
    """Every field but ``expected_version`` is optional; only the ones the
    caller actually sent should reach ``update_type`` — see
    ``endpoints/api/types.py``'s ``model_dump(exclude_unset=True)``.

    ``force``/``orphaned`` are not columns and never reach ``**changes`` —
    they are the two retries a 409 from :mod:`sm_records.services.schema_change`
    asks for (design §8.2, §8.8), read separately by the endpoint and passed
    to ``update_type`` as their own keyword arguments.
    """

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
    force: bool = False
    orphaned: str | None = None


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
    invalid: list[dict[str, str]]
    """Empty when the record satisfies the current schema. Non-empty marks it
    "invalid under current schema" without hiding it (design §8.3) — set by a
    ``force``d restrictive schema change or a rollback the record no longer
    fits. Straight from ``read_view``'s own ``invalid`` list."""


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


class RecordRevisionDetailRead(RevisionRead):
    """``GET .../revisions/{id}``'s response — the list entry plus the
    payload it snapshotted, for the read-only preview before restoring it."""

    data: dict[str, Any]


class RecordRevisionRestoreRequest(SQLModel):
    expected_version: int


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
        allowed_roles=list(rtype.allowed_roles or []),
        record_count=record_count,
        trashed_record_count=trashed_record_count,
        reindex_pending=pending_map(rtype),
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
        invalid=view["invalid"],
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


def record_revision_detail_read(revision: RecordRevision) -> RecordRevisionDetailRead:
    return RecordRevisionDetailRead(
        id=revision.id,
        version=revision.version,
        schema_version=revision.schema_version,
        event=revision.event.value,
        display_title=revision.display_title,
        created_at=revision.created_at,
        created_by=revision.created_by,
        data=dict(revision.data or {}),
    )
