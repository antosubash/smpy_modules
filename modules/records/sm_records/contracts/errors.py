"""The shapes a refusal takes on the wire, as models the schema can name.

Every one of these is already produced by
:mod:`sm_records.endpoints.api._error_bodies`; what was missing was a
*declaration* of them, so ``GET /openapi.json`` documented only ``200``/``201``
/``204`` and FastAPI's own ``422`` and a generated client saw none of the
``400``/``403``/``404``/``409``/``413`` contract the reference describes.

Deliberately four models and not one per row of that table. The table has
thirty-nine rows because it enumerates *occasions*; the wire has a handful of
shapes, and a client branches on the shape. Which occasions a given status
covers is prose, and rides in the OpenAPI ``description`` that
:mod:`sm_records.endpoints.api._responses` assembles from the same table.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

__all__ = [
    "ConflictBody",
    "ErrorDetail",
    "FieldError",
    "QueryErrorBody",
    "ValidationErrorBody",
]


class ErrorDetail(SQLModel):
    """The flat refusal: ``{"detail": "..."}``.

    What a 401, a 403, a 404, a 413 and a 500 all send, and what the public
    API sends for *every* refusal — there, deliberately without the ``field``
    and ``reason`` the admin grammar adds (§10).
    """

    detail: str


class FieldError(SQLModel):
    """One entry of a 422's ``errors``. ``field`` is the payload key an editor
    shows, or ``__root__`` for a problem with the payload as a whole."""

    field: str
    message: str


class ValidationErrorBody(SQLModel):
    """A 422 from this module: a payload, a field definition or a type that
    does not satisfy its own rules.

    Distinct from FastAPI's ``HTTPValidationError``, which is what a bad
    *query parameter* produces — ``?page=0`` is that one, a bad ``data`` is
    this one. Both are 422s and the reference table lists both.
    """

    detail: str
    errors: list[FieldError] = SQLField(default_factory=list)


class QueryErrorBody(SQLModel):
    """A refused ``?filter=``/``?sort=``/``?expand=`` term.

    ``field`` and ``reason`` are present when the grammar can name them
    (``unknown``, ``not_indexed``, ``unsupported_op``, ``bad_value``,
    ``not_a_relation``, ``reindexing``) and absent otherwise — a malformed
    term, or a cap exceeded, is about the *request* rather than about one
    field. The public API strips both from every refusal.
    """

    detail: str
    field: str | None = None
    reason: str | None = None


class ConflictBody(SQLModel):
    """A 409. One model rather than six, because the extra key is what says
    which conflict it was and a client has to look at it either way.

    ``current`` is the row a stale write collided with (``RecordRead`` or
    ``TypeRead``); ``referrers``/``hidden``/``more`` a delete blocked by
    ``on_delete: restrict``; ``report`` a schema change that would leave
    records invalid; ``conflicts`` a re-added key that still holds orphaned
    values; ``field``/``reason`` a filter on a field mid-rebuild. A slug or
    ``unique`` collision carries none of them.
    """

    detail: str
    current: dict[str, Any] | None = None
    referrers: list[str] | None = None
    hidden: int | None = None
    more: int | None = None
    report: dict[str, Any] | None = None
    conflicts: dict[str, int] | None = None
    field: str | None = None
    reason: str | None = None
