"""Which statuses each kind of route can produce, and the ``responses=`` for it.

The occasions themselves are :mod:`sm_records.endpoints.api._error_table`; the
shapes are :mod:`sm_records.contracts.errors`. What is here is the join: a
handful of bundles named for what a route *is* rather than for the codes it
returns, so adding a route means choosing a noun, and the description under
each status is assembled from the table rather than written a second time.

Four shapes and not thirty-nine, because the table enumerates *occasions* and
the wire has shapes — a client branches on the shape and reads the prose.
"""

from __future__ import annotations

from typing import Any, Final

from sm_records.contracts.errors import (
    ConflictBody,
    ErrorDetail,
    QueryErrorBody,
    ValidationErrorBody,
)
from sm_records.endpoints.api._error_table import ERROR_TABLE

__all__ = [
    "ADMIN_READ",
    "IMPORT",
    "LISTING",
    "PUBLIC_READ",
    "TYPE_WRITE",
    "WRITE",
    "responses",
]

_MODELS: Final[dict[int, Any]] = {
    400: QueryErrorBody,
    401: ErrorDetail,
    403: ErrorDetail,
    404: ErrorDetail,
    409: ConflictBody,
    413: ErrorDetail,
    422: ValidationErrorBody,
    500: ErrorDetail,
}
"""Which shape each status sends. A status with no entry would be documented
with a description and no model, which is the honest answer for one whose body
this module does not own."""


def _description(status: int) -> str:
    """Every documented occasion for one status, as one markdown list.

    Assembled rather than written, so a new row in ``ERROR_TABLE`` reaches the
    schema without anybody remembering a second place to edit.
    """
    rows = [row for row in ERROR_TABLE if row.status == status]
    if len(rows) == 1:
        return f"{rows[0].when} — {rows[0].body}"
    return "\n".join(f"* {row.when} — {row.body}" for row in rows)


def responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """The ``responses=`` for a route that can produce ``statuses``.

    Passed to an ``APIRouter`` wherever a whole router shares a set: FastAPI
    merges the router's into every route's, so a per-route argument only has
    to name what is *extra*.
    """
    out: dict[int | str, dict[str, Any]] = {}
    for status in sorted(set(statuses)):
        entry: dict[str, Any] = {"description": _description(status)}
        model = _MODELS.get(status)
        if model is not None:
            entry["model"] = model
        out[status] = entry
    return out


_ALWAYS: Final = (401, 403, 500)
"""Every route under ``/api/records/*``: no session, a missing permission, and
the JSON 500 ``RecordsErrorRoute`` answers anything unanticipated with."""

ADMIN_READ: Final = (*_ALWAYS, 404)
"""A read addressed by a type key or a uuid — the 404 covers both, and the 403
covers ``allowed_roles`` as well as the static permission."""

LISTING: Final = (*ADMIN_READ, 400, 409)
"""A read that takes the ``?filter=``/``?sort=`` grammar: 400 for a term it
refuses, 409 for a field mid-rebuild."""

WRITE: Final = (*ADMIN_READ, 409, 413, 422)
"""A record write: optimistic concurrency and claim conflicts, the body
ceiling, and the payload validator."""

TYPE_WRITE: Final = (*ADMIN_READ, 409, 413, 422)
"""A schema write. The same statuses as :data:`WRITE`, named separately
because the *occasions* differ — a schema-change refusal, a changed
``collection`` — and the next code to diverge will diverge here."""

IMPORT: Final = (*ADMIN_READ, 400, 409, 413, 422)
"""An import: the parse failure of a file that is not what it claims, plus
both ceilings and the per-row report."""

PUBLIC_READ: Final = (400, 404)
"""The anonymous surface. **No 401 and no 403**: it needs no session, and a
type it will not serve is the same 404 as one that does not exist (§10)."""
