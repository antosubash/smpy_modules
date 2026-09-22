"""HTTP-facing DTOs for design §8's schema-change pipeline.

Split from ``contracts/schemas.py`` for the 300-line cap — the seam is real:
that module is "what does one row look like on the wire", this one is "what
does a proposed change to one look like", mirroring
:mod:`sm_records.schema.changes` field for field.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import SQLModel

from sm_records.models import RecordTypeRevision
from sm_records.schema.changes import DryRunReport, SchemaChange, SchemaDiff
from sm_records.schema.types import ChangeClass

__all__ = [
    "DryRunReportRead",
    "FailingRecordRead",
    "SchemaChangeRead",
    "SchemaPreviewJobRead",
    "SchemaPreviewRead",
    "SchemaPreviewRequest",
    "TypeRestoreRequest",
    "TypeRevisionListResponse",
    "TypeRevisionRead",
    "dry_run_report_read",
    "schema_preview_job_read",
    "schema_preview_read",
    "type_revision_read",
]


class SchemaChangeRead(SQLModel):
    """One entry of a ``SchemaPreviewRead.changes`` list. Mirrors
    :class:`sm_records.schema.changes.SchemaChange` field for field."""

    kind: ChangeClass
    field_key: str
    what: str
    before: Any = None
    after: Any = None


class FailingRecordRead(SQLModel):
    uuid: str
    display_title: str
    errors: list[dict[str, str]]


class DryRunReportRead(SQLModel):
    checked: int
    failing: int
    sample: list[FailingRecordRead]
    orphaned_conflicts: dict[str, int]
    duplicates: dict[str, int] = {}
    """Keys gaining ``unique`` that some records already hold duplicates of,
    and how many records hold one. Already counted inside ``failing``; kept
    apart so the panel can say that ``force`` does not leave these
    recoverable — see :class:`~sm_records.schema.changes.DryRunReport`."""
    clean: bool


class SchemaPreviewRequest(SQLModel):
    """``POST /types/{key}/schema/preview``'s body. ``display_field``/
    ``slug_field`` are optional and only affect the diff when the caller
    actually sends them — see ``endpoints/api/types.py``'s
    ``model_dump(exclude_unset=True)``, which is what tells a pointer the
    caller left out apart from one explicitly set back to its current value."""

    fields: list[dict[str, Any]]
    display_field: str | None = None
    slug_field: str | None = None
    rescan: bool = False
    """Scan the records even when the diff is empty — the "Check records"
    button, which asks "which records do not fit the schema *as it is*".

    Without it that question has no answer: ``needs_dry_run`` sees nothing
    restrictive in an empty diff and ``change_report`` short-circuits to
    ``checked=N, failing=0``, which reads as "everything is fine" when it
    means "nothing was checked". That is exactly the state a forced
    restrictive change leaves behind, and re-deriving the worklist afterwards
    is what the panel needs."""


class SchemaPreviewRead(SQLModel):
    """Writes nothing — classifies the proposed ``fields`` and dry-runs it
    against the type's records (design §8.9)."""

    kind: ChangeClass
    changes: list[SchemaChangeRead]
    report: DryRunReportRead


class SchemaPreviewJobRead(SQLModel):
    """``GET /types/{key}/schema/preview/{job}`` — a deferred preview's state.

    ``status`` is ``running``, ``done`` or ``failed``. ``checked``/``total``
    are the progress the scan reports per batch, for the "checked N of M" the
    editor shows. ``preview`` is the ordinary :class:`SchemaPreviewRead` and
    is present exactly when ``status`` is ``done`` — the same body the
    synchronous path returns, so a client renders one shape either way.
    """

    job: str
    status: str
    checked: int
    total: int
    preview: SchemaPreviewRead | None = None
    error: str | None = None


class TypeRevisionRead(SQLModel):
    """One snapshot of a type's schema, from ``GET /types/{key}/revisions``."""

    id: int
    version: int
    schema_version: int
    fields: list[dict[str, Any]]
    display_field: str | None
    slug_field: str | None
    created_at: datetime
    created_by: str | None


class TypeRevisionListResponse(SQLModel):
    """One page of a type's schema history.

    Paged like the record list and for a plainer reason than that one: type
    revisions are never pruned (they are what a rollback reads), so without a
    page the response grows for the lifetime of the type and is re-downloaded
    on every open of the schema screen. ``total`` is exact rather than capped
    — the count is per type and cheap, and a "312+" here would be useless to
    a panel whose job is to find one particular past version.
    """

    items: list[TypeRevisionRead]
    total: int = 0
    page: int = 1
    page_size: int = 0


class TypeRestoreRequest(SQLModel):
    """A schema rollback goes through the same pipeline as any other change
    (§8.6) — same body shape and 409s as ``TypeUpdate``."""

    expected_version: int
    force: bool = False
    orphaned: str | None = None


def type_revision_read(revision: RecordTypeRevision) -> TypeRevisionRead:
    return TypeRevisionRead(
        id=revision.id,
        version=revision.version,
        schema_version=revision.schema_version,
        fields=list(revision.fields or []),
        display_field=revision.display_field,
        slug_field=revision.slug_field,
        created_at=revision.created_at,
        created_by=revision.created_by,
    )


def dry_run_report_read(report: DryRunReport) -> DryRunReportRead:
    """The wire shape of a :class:`~sm_records.schema.changes.DryRunReport`.

    Built rather than ``dataclasses.asdict``: ``clean`` is a computed
    property, not a field, and ``asdict`` would drop it — the one thing the
    UI's summary line actually reads (``DryRunReportView``).
    """
    return DryRunReportRead(
        checked=report.checked,
        failing=report.failing,
        sample=[
            FailingRecordRead(uuid=r.uuid, display_title=r.display_title, errors=list(r.errors))
            for r in report.sample
        ],
        orphaned_conflicts=dict(report.orphaned_conflicts),
        duplicates=dict(report.duplicates),
        clean=report.clean,
    )


def _schema_change_read(change: SchemaChange) -> SchemaChangeRead:
    return SchemaChangeRead(
        kind=change.kind,
        field_key=change.field_key,
        what=change.what,
        before=change.before,
        after=change.after,
    )


def schema_preview_read(diff: SchemaDiff, report: DryRunReport) -> SchemaPreviewRead:
    return SchemaPreviewRead(
        kind=diff.kind,
        changes=[_schema_change_read(c) for c in diff.changes],
        report=dry_run_report_read(report),
    )


def schema_preview_job_read(job: Any) -> SchemaPreviewJobRead:
    """A :class:`~sm_records.services.preview_jobs.PreviewJob` on the wire.

    ``Any`` rather than the dataclass: the contracts layer is the module's
    public surface and an in-process registry entry is not part of it —
    importing the type here would make a request-shape module depend on a
    services one for nothing but an annotation.
    """
    preview = (
        schema_preview_read(job.diff, job.report)
        if job.diff is not None and job.report is not None
        else None
    )
    return SchemaPreviewJobRead(
        job=job.id,
        status=job.status,
        checked=job.checked,
        total=job.total,
        preview=preview,
        error=job.error,
    )
