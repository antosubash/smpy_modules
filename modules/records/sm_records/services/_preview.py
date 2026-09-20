"""What a schema *preview* contributes to the change beside it — §8.9, §18 Q2.

Split out of :mod:`sm_records.services.schema_change` for the 300-line cap,
and both halves are self-contained rules worth reading on their own: the
``MISSING``-vs-``None`` sentinel that decides whether a pointer was sent at
all, and the one condition under which an apply may take its report from a
preview that already ran instead of scanning the type a second time.
"""

from __future__ import annotations

from typing import Any

from sm_records.constants import REINDEX_ALL
from sm_records.models import RecordType
from sm_records.schema.changes import DryRunReport, SchemaChange
from sm_records.schema.types import ChangeClass
from sm_records.services import preview_jobs
from sm_records.settings import RecordsSettings

__all__ = ["MISSING", "pointer_preview_changes", "reused_report"]

MISSING: Any = object()
"""Sentinel for a pointer argument a caller did not send at all, as opposed
to one explicitly re-sent unchanged or explicitly cleared to ``None`` — both
of which are legitimate *values*, so "left out" needs its own state."""


def pointer_preview_changes(
    rtype: RecordType, display_field: Any, slug_field: Any
) -> list[SchemaChange]:
    """A pointer-only edit invalidates no record, so it never triggers a dry
    run — but a ``display_field`` change denormalises every record's
    ``display_title`` (§18 Q2), the same whole-type rebuild ``apply``
    enqueues under ``REINDEX_ALL``. Surfaced here as a single index-affecting
    entry, so "Preview changes" shows it even when ``fields`` itself did not
    move.

    ``slug_field`` is accepted for the same request shape but never adds an
    entry: a slug already handed out is an address, not a denormalisation,
    and ``apply`` never enqueues anything for changing it.
    """
    if display_field is MISSING or display_field == rtype.display_field:
        return []
    return [
        SchemaChange(
            kind=ChangeClass.INDEX_AFFECTING,
            field_key=REINDEX_ALL,
            what="display_field_changed",
            before=rtype.display_field,
            after=display_field,
        )
    ]


def reused_report(
    rtype: RecordType,
    *,
    current_version: int,
    fields_raw: Any,
    display_field: Any,
    slug_field: Any,
    settings: RecordsSettings,
    drop_keys: frozenset[str],
) -> DryRunReport | None:
    """A finished preview job's report, if one describes exactly this apply.

    :func:`sm_records.services.preview_jobs.reusable` carries the argument for
    why the ``version`` check makes it the same question — and what it does
    not cover, which is the TTL's job. Two conditions are added here.

    ``drop_keys`` refuses the reuse outright: an ``orphaned="discard"`` apply
    judges every record *without* the values it is about to throw away
    (§8.8), and no preview ran under that reading — the preview endpoint has
    no ``orphaned`` argument at all. Reusing one would refuse a change for
    content the operator has already said to discard.

    ``None`` means "scan", which is always correct and is what an install with
    ``preview_job_ttl_seconds = 0`` always gets.
    """
    if drop_keys:
        return None
    job = preview_jobs.reusable(
        type_key=rtype.key,
        type_version=current_version,
        signature=preview_jobs.fields_hash(fields_raw, display_field, slug_field),
        ttl_seconds=settings.preview_job_ttl_seconds,
    )
    return job.report if job is not None else None
