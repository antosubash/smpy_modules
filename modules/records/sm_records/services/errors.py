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


class FieldsLocked(Conflict):
    """A ``fields`` edit on a type that already holds records.

    Design §16: until Phase 3 lands — the classification of §8.2, the dry-run
    and the index-table migration of §8.5 — **a type's ``fields`` are
    read-only once it holds a record**. The guard is one check, and it exists
    because an unguarded ``fields`` write on a populated type is precisely the
    data loss the whole of §8 is written to prevent.
    """

    def __init__(self, type_key: str, record_count: int) -> None:
        super().__init__(
            f"type {type_key!r} holds {record_count} record(s), so its fields are read-only "
            "until schema evolution ships (design §16)"
        )


class ReferencedByOthers(Conflict):
    """A delete blocked by ``on_delete: restrict`` relations pointing at it.

    ``referrers`` is a list of record uuids rather than ids: uuid is what the
    API and the relation payload speak (design §5), so the delete dialog can
    link straight to each blocker. Reused for a type delete, where the strings
    are type keys — the caller knows which it asked about.
    """

    def __init__(self, detail: str, referrers: list[str]) -> None:
        self.referrers = referrers
        super().__init__(detail)


__all__ = [
    "Conflict",
    "FieldsLocked",
    "Forbidden",
    "NotFound",
    "RecordsError",
    "ReferencedByOthers",
    "ValidationFailed",
]
