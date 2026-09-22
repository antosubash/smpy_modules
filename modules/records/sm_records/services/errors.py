"""The exceptions the services layer raises, and nothing else.

Services never import FastAPI. A service that raised ``HTTPException``
would be unusable from the reindex CLI command, from a background task and
from another module's code — all three of which design §8.9 and §7.6 require —
and it would make "what does this fail with" a question about the transport
rather than about the domain. The endpoints layer owns the mapping, and
:attr:`RecordsError.status_code` is the whole of what it needs to do it.
"""

from __future__ import annotations

from typing import Any


class RecordsError(Exception):
    """Base for every failure the services layer reports deliberately."""

    status_code: int = 400

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class NotFound(RecordsError):  # noqa: N818 - HTTP vocabulary, deliberately
    status_code = 404


class Conflict(RecordsError):  # noqa: N818 - HTTP vocabulary, deliberately
    """A write that lost a race, or one whose precondition no longer holds.

    ``current`` carries the row as it now stands, so an optimistic-concurrency
    409 can hand the editor something to diff against rather than only telling
    it to try again — design §5.1 and §8.6. It is ``None`` for the conflicts
    that are not about a stale read (a taken slug, a duplicate ``unique``
    value), because there is no single row the caller should reload.
    """

    status_code = 409

    def __init__(self, detail: str, *, current: Any | None = None) -> None:
        self.current = current
        super().__init__(detail)


class ValidationFailed(RecordsError):  # noqa: N818 - HTTP vocabulary, deliberately
    """A payload or a schema that does not satisfy its definition.

    ``errors`` is the flat ``[{"field": ..., "message": ...}]`` shape
    :class:`sm_records.schema.compile.PayloadValidationError` produces, kept
    unchanged so the generic form renderer has one shape to key on whether the
    complaint came from pydantic, from a relation target that does not exist,
    or from a ``unique`` collision.
    """

    status_code = 422

    def __init__(self, detail: str, errors: list[dict[str, str]] | None = None) -> None:
        self.errors = errors if errors is not None else [{"field": "__root__", "message": detail}]
        super().__init__(detail)


class Forbidden(RecordsError):  # noqa: N818 - HTTP vocabulary, deliberately
    status_code = 403


class ReferencedByOthers(Conflict):
    """A delete blocked by ``on_delete: restrict`` relations pointing at it.

    ``referrers`` is a list of record uuids rather than ids: uuid is what the
    API and the relation payload speak (design §5), so the delete dialog can
    link straight to each blocker. Reused for a type delete, where the strings
    are type keys — the caller knows which it asked about.

    ``hidden`` counts blockers whose *type* narrows ``allowed_roles`` past the
    caller, and they are deliberately **not** in ``referrers``: the referrers
    panel counts those and refuses to name them
    (``contracts.relations.ReferrersResponse``), and a refusal that named them
    anyway would hand back exactly the identifier the panel goes out of its
    way to withhold. ``more`` is how many *visible* blockers were left off the
    list, which is capped for the same reason ``ImportReport`` caps its errors
    — a hundred thousand referrers is not a response anybody can read.
    ``total`` is all three and is the number ``detail`` speaks. It is carried
    as a field rather than left for a client to parse back out of the
    sentence, which is also why the sentence no longer names the blocked
    record: that uuid is in the URL of a single-record delete and in
    ``BulkFailure.uuid`` of a batch, and interpolating it made the bulk
    refusal panel print the same 32-hex string twice with nothing else on the
    line. Defaults to the three numbers added up, for the type-delete caller
    that has a plain list and no cap.
    """

    def __init__(
        self,
        detail: str,
        referrers: list[str],
        *,
        hidden: int = 0,
        more: int = 0,
        total: int | None = None,
    ) -> None:
        self.referrers = referrers
        self.hidden = hidden
        self.more = more
        self.total = total if total is not None else len(referrers) + hidden + more
        super().__init__(detail)


class SchemaChangeRefused(Conflict):
    """A restrictive change would leave records invalid (§8.2). Carries the
    dry-run report so the response can show the count and a sample; the
    caller re-sends with a ``default`` that makes every row valid, or
    ``force=True`` to apply and mark the failures rather than mutate them."""

    def __init__(self, report: object, detail: str) -> None:
        super().__init__(detail)
        self.report = report


class BulkRefused(Conflict):
    """A bulk action at least one of its records would not take.

    Carries the :class:`~sm_records.contracts.bulk.BulkReport` naming every
    one of them, because that is what the caller acts on: bulk is
    all-or-nothing, so the answer to a refusal is to deselect what the report
    lists and send the rest.

    A ``Conflict`` — the *batch* conflicts with the state its records are in —
    although the individual refusals inside it carry their own statuses, which
    ``BulkFailure.status`` reports per uuid. Raised rather than returned, so
    ``RecordsErrorRoute`` rolls the request's session back: that rollback is
    what makes "nothing was written" true rather than aspirational, exactly as
    it does for an ``on_error=abort`` import.
    """

    def __init__(self, report: object, detail: str) -> None:
        super().__init__(detail)
        self.report = report


class PayloadTooLarge(RecordsError):  # noqa: N818 - HTTP vocabulary, deliberately
    """More than one request may carry: an uploaded import file over
    ``max_import_bytes``, a file holding more than ``max_import_rows`` rows,
    or a bulk action naming more than ``max_bulk_records`` records.

    413 and **before parsing** (and, for bulk, before a record is touched),
    which is the whole point: a limit checked after ``json.loads`` is a limit
    that has already allocated the thing it was meant to refuse.
    """

    status_code = 413


class ImportParseFailed(RecordsError):  # noqa: N818 - HTTP vocabulary, deliberately
    """A file that is not the format it claims to be.

    400 rather than 422: nothing here is a judgement about the *content*
    against a schema — the bytes did not parse, or the header names a column
    no field has. ``detail`` names the line or row, because "invalid JSON" on
    a 40 MB file is not an actionable message.
    """

    status_code = 400


class ImportRefused(RecordsError):  # noqa: N818 - HTTP vocabulary, deliberately
    """``on_error=abort`` found a bad row, so the whole import is off.

    Carries the same :class:`~sm_records.contracts.io.ImportReport` a
    successful run returns — a refusal the caller can read row by row and fix,
    rather than a message about the first thing that went wrong. Raised rather
    than returned so ``RecordsErrorRoute`` rolls the request's session back:
    that rollback is what makes ``abort`` mean *all or nothing* instead of
    "everything up to the bad row".
    """

    status_code = 422

    def __init__(self, report: object, detail: str) -> None:
        super().__init__(detail)
        self.report = report


class OrphanedKeyConflict(Conflict):
    """A field is being added whose key still holds orphaned values on some
    records (§8.8). Neither restoring nor discarding may happen silently;
    the caller re-sends with ``orphaned="restore"`` or ``orphaned="discard"``."""

    def __init__(self, conflicts: dict[str, int]) -> None:
        keys = ", ".join(f"{k} ({n} record(s))" for k, n in conflicts.items())
        super().__init__(f"orphaned values exist for: {keys}; choose restore or discard")
        self.conflicts = conflicts


__all__ = [
    "BulkRefused",
    "Conflict",
    "Forbidden",
    "ImportParseFailed",
    "ImportRefused",
    "NotFound",
    "OrphanedKeyConflict",
    "PayloadTooLarge",
    "RecordsError",
    "ReferencedByOthers",
    "SchemaChangeRefused",
    "ValidationFailed",
]
