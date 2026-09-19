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

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from sm_records.index.reindex import pending_map
from sm_records.models import Record, RecordRevision, RecordType
from sm_records.schema.fields import FieldDefinition
from sm_records.services._payload import field_defs
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
    "record_list_read",
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
    fits. Straight from ``read_view``'s own ``invalid`` list.

    **Always empty on a list response** — filling it costs a validator pass
    per row (:func:`record_list_read`); the badge belongs to the editor, which
    reads one record."""


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


def record_read(
    rtype: RecordType,
    record: Record,
    *,
    with_invalid: bool = True,
    defs: list[FieldDefinition] | None = None,
) -> RecordRead:
    """The one lenient read every caller gets: ``read_view`` fills a missing
    key from ``default`` and flags a row stamped at an old schema version
    rather than failing it (design §8.3).

    ``with_invalid``/``defs`` are ``read_view``'s — see
    :func:`record_list_read`, the one caller that turns the badge off.

    ``data`` still carries the reserved ``_orphaned`` sub-key when the row has
    one: these screens are the admin's, and the raw editor shows a deleted
    field's content on purpose (§8.2 — that is what makes the deletion
    undoable). **Phase 4's public read API must strip it** before serving a
    record to anonymous callers.
    """
    view = read_view(rtype, record, with_invalid=with_invalid, defs=defs)
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


def record_list_read(rtype: RecordType, records: Sequence[Record]) -> list[RecordRead]:
    """A page of records, read once per *type* rather than once per row.

    Two things the per-record path does that a list must not: it re-validates
    the type's stored field definitions (``field_defs``) for every item, and it
    runs the compiled payload validator for every item to fill ``invalid``. On
    a page of fifty that is fifty of each, to produce a badge no list screen
    shows — so ``invalid`` is ``[]`` here by construction, and a caller that
    needs it opens the record (design §8.3's "marked, not hidden" is about the
    editor). ``defs`` is computed once and shared.
    """
    defs = field_defs(rtype)
    return [record_read(rtype, record, with_invalid=False, defs=defs) for record in records]


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
