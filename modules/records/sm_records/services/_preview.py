"""Pointer-only additions to a schema preview's diff — design §8.9, §18 Q2.

Split out of :mod:`sm_records.services.schema_change` for the 300-line cap.
:func:`~sm_records.services.schema_change.preview` is the only caller; kept
separate because the ``MISSING``-vs-``None`` sentinel rule is a self-contained
thing worth reading on its own.
"""

from __future__ import annotations

from typing import Any

from sm_records.constants import REINDEX_ALL
from sm_records.models import RecordType
from sm_records.schema.changes import SchemaChange
from sm_records.schema.types import ChangeClass

__all__ = ["MISSING", "pointer_preview_changes"]

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
