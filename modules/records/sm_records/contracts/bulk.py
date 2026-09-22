"""Wire shapes for the two multi-record writes: bulk actions and empty trash.

The whole of the confirmation semantics is in :class:`BulkReport`, and it is
worth stating once here because nothing else in this module works this way.

**Bulk is all-or-nothing.** Every record named goes through the single-record
service — the same ``allowed_roles`` narrowing, the same ``on_delete``
cascade, the same unique claims, the same revision and the same event — and
the first refusal does not stop the pass: every record is attempted, every
refusal is collected, and then *nothing* is written. The alternative is a
partial success whose report the operator has to reconcile against a list
that has already changed underneath them, on an action they cannot undo in
one step.

So a refusal is a 409 carrying this report rather than a 200 carrying counts,
and the report names each failing uuid with the status and the message the
same action on that record alone would have answered. That is what the
selection UI deselects by and retries with — which is the point: an
all-or-nothing batch is only usable if the refusal says exactly which ticks
to untick.

A run that refuses nothing answers :class:`BulkResult`, which counts what it
did rather than listing it: the caller named the uuids and is about to reload
the list anyway. ``cascaded`` is the one number it could not have predicted.
"""

from __future__ import annotations

import enum

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

__all__ = [
    "BulkAction",
    "BulkFailure",
    "BulkReport",
    "BulkRequest",
    "BulkResult",
    "TrashEmptied",
]


class BulkAction(str, enum.Enum):  # noqa: UP042
    """What one bulk request does to every record it names.

    Five and not "any endpoint, repeated": each of these is a whole-record
    transition with no body of its own, which is what makes applying it to a
    selection meaningful. Editing a *payload* across a selection is not here
    — there is no field-level merge that is right for every type, and the
    import path already expresses "apply this file to these records".
    """

    TRASH = "trash"
    RESTORE = "restore"
    PURGE = "purge"
    PUBLISH = "publish"
    UNPUBLISH = "unpublish"


class BulkRequest(SQLModel):
    """The body of ``POST /types/{key}/records/bulk``.

    ``uuids`` is capped at ``RecordsSettings.max_bulk_records`` and repeats
    are collapsed, first occurrence winning: a selection model that sends the
    same record twice means it once, and the second turn would otherwise fail
    as "already in the trash" and refuse the whole batch.

    ``expected_versions`` is optional and partial — a uuid it does not mention
    is applied at whatever version the row currently holds. Given, it is the
    same optimistic-concurrency check ``PUT /records/{uuid}`` makes, per
    record: a selection made against a list someone else has since edited is
    refused with that record named rather than silently applied to a row the
    operator never saw. ``publish``/``unpublish`` bump the version like any
    other write; ``trash``/``restore``/``purge`` do not, and check it without
    bumping it.
    """

    action: BulkAction
    uuids: list[str] = SQLField(min_length=1)
    expected_versions: dict[str, int] | None = None


class BulkFailure(SQLModel):
    """One record the batch could not apply, and why.

    ``status`` is what the same action on that record *alone* would have
    answered — 404 for a uuid that is not there, 403 where a type's
    ``allowed_roles`` exclude the caller, 409 for a stale version or a
    ``restrict`` relation, 422 for a payload the current schema no longer
    accepts. The batch's own status is always 409: the request as a whole
    conflicts with the state the records are in.
    """

    uuid: str
    status: int
    message: str


class BulkReport(SQLModel):
    """The ``report`` a refused bulk action carries. Nothing was written.

    ``failed`` is not capped: ``uuids`` already is, so the longest report
    possible is one line per record the caller itself named.
    """

    action: BulkAction
    requested: int
    failed: list[BulkFailure] = SQLField(default_factory=list)


class BulkResult(SQLModel):
    """What a bulk action that refused nothing did.

    ``requested`` counts distinct uuids after the repeats are collapsed, so it
    is the number ``changed`` is compared against. ``cascaded`` counts records
    a ``trash`` reached through an ``on_delete: cascade`` relation and which
    the request therefore never named — zero for every other action, and the
    one number the caller could not have worked out for itself.
    """

    action: BulkAction
    requested: int
    changed: int
    cascaded: int = 0


class TrashEmptied(SQLModel):
    """What ``POST /types/{key}/records/trash/empty`` purged.

    ``filtered`` says whether a ``?filter=`` narrowed it, so a caller — and
    the screen behind it — can say "12 trashed records matching this filter"
    rather than claiming the trash is now empty when it is not.
    """

    purged: int
    filtered: bool = False
