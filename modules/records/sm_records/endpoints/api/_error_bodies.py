"""Turning one :class:`~sm_records.services.errors.RecordsError` into its body.

Split from :mod:`sm_records.endpoints.api._errors` for the 300-line cap, along
a seam that module's docstring already drew in prose: that one decides *which*
answer a router gives — JSON for ``/api/records/*``, the host's rendered error
page for the Inertia screens — and owns the rollback; this one knows what each
exception looks like on the wire. The ``errors`` list of a 422, the
``referrers``/``hidden``/``more`` of a blocked delete, the dry-run report
riding along with a refused schema change, the ``conflicts`` map of an
orphaned key, and the ``current`` row an optimistic-concurrency 409 hands back.

``Conflict.current`` is the one case that needs more than the exception's own
attributes: it holds the ORM row a stale write collided with, and the
contract wants it serialised as a ``RecordRead`` or ``TypeRead``. That read
runs on a fresh, short-lived session rather than the request's own, and it
happens *before* the rollback — a rollback expires every instance in the
request's identity map, and refreshing one from async code outside a greenlet
is a ``MissingGreenlet``, not a response.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from sm_records.contracts.schema_change import dry_run_report_read
from sm_records.contracts.schemas import record_read, type_read
from sm_records.index.query import QueryError
from sm_records.models import RecordType, table_sets
from sm_records.services.errors import (
    BulkRefused,
    Conflict,
    ImportRefused,
    NotFound,
    OrphanedKeyConflict,
    RecordsError,
    ReferencedByOthers,
    SchemaChangeRefused,
    ValidationFailed,
)
from sm_records.services.types import get_type_by_id, record_counts

__all__ = ["response_for"]


def _document_classes() -> tuple[type, ...]:
    """Every declared table set's document class.

    ``isinstance(current, Record)`` was enough while there was one; since
    Phase 5 §6 a conflict may carry a collection's record, whose class is a
    sibling of the global one and not a subclass of it. Read per call rather
    than memoised at import, because a host declares its collections before
    ``create_app`` and this module may be imported either side of that.
    """
    return tuple(tables.record for tables in table_sets())


async def _current_dto(db: Any, current: Any) -> Any:
    if isinstance(current, RecordType):
        live, trashed, invalid = await record_counts(db, current)
        return type_read(current, live, trashed, invalid).model_dump(mode="json")
    if isinstance(current, _document_classes()):
        rtype = await get_type_by_id(db, current.type_id)
        return record_read(rtype, current).model_dump(mode="json")
    return current


async def _conflict_body(request: Request, exc: Conflict) -> dict[str, Any]:
    body: dict[str, Any] = {"detail": exc.detail}
    if exc.current is None:
        return body
    session = request.app.state.sm.db.session_factory()
    try:
        body["current"] = await _current_dto(session, exc.current)
    except NotFound:
        # The writer that won the race deleted the row outright. "It is gone"
        # is not something this response can express, but a 409 without
        # ``current`` is the honest half of it — and it beats the 500 that
        # letting the lookup escape used to produce.
        pass
    finally:
        await session.close()
    return body


async def response_for(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, ValidationFailed):
        return JSONResponse(
            {"detail": exc.detail, "errors": exc.errors}, status_code=exc.status_code
        )
    if isinstance(exc, ReferencedByOthers):
        # ``total``, ``hidden`` and ``more`` are always present, the last two
        # at zero when there is nothing to say: a client that has to tell "no
        # hidden blockers" from "this server does not report them" would
        # guess, and the number it would guess about is the difference between
        # ``total`` and the list it can show. ``total`` is a field because
        # ``detail`` is a sentence, and a count read back out of prose is a
        # count that breaks when the prose is translated.
        return JSONResponse(
            {
                "detail": exc.detail,
                "total": exc.total,
                "referrers": exc.referrers,
                "hidden": exc.hidden,
                "more": exc.more,
            },
            status_code=exc.status_code,
        )
    if isinstance(exc, SchemaChangeRefused):
        # Checked ahead of the generic ``Conflict`` branch below: this is one,
        # but its whole point is the dry-run report riding along with it
        # (design §8.2), not a ``current`` row to reload.
        report = dry_run_report_read(exc.report).model_dump(mode="json")
        return JSONResponse({"detail": exc.detail, "report": report}, status_code=exc.status_code)
    if isinstance(exc, BulkRefused):
        # Checked ahead of the generic ``Conflict``, which it is one of, for
        # the same reason as the two branches around it: the useful part of
        # the refusal is the report riding with it — which uuid refused, and
        # what the same action on it alone would have answered — and not a
        # ``current`` row, of which a batch has as many as it has records.
        return JSONResponse(
            {"detail": exc.detail, "report": exc.report.model_dump(mode="json")},
            status_code=exc.status_code,
        )
    if isinstance(exc, ImportRefused):
        # An ``on_error=abort`` import that found a bad row. Like
        # ``SchemaChangeRefused`` above, the useful part of the refusal is the
        # report riding with it — the caller fixes the rows it names and
        # re-posts the same file — and, like that one, the rollback below is
        # what makes "nothing was imported" true rather than aspirational.
        return JSONResponse(
            {"detail": exc.detail, "report": exc.report.model_dump(mode="json")},
            status_code=exc.status_code,
        )
    if isinstance(exc, OrphanedKeyConflict):
        # Same reasoning as above: a ``Conflict`` subclass whose payload is
        # its own (design §8.8), not the generic ``current`` row.
        return JSONResponse(
            {"detail": exc.detail, "conflicts": exc.conflicts}, status_code=exc.status_code
        )
    if isinstance(exc, Conflict):
        return JSONResponse(await _conflict_body(request, exc), status_code=exc.status_code)
    if isinstance(exc, QueryError):
        status = 409 if exc.reason == "reindexing" else 400
        return JSONResponse(
            {"detail": str(exc), "field": exc.field, "reason": exc.reason}, status_code=status
        )
    assert isinstance(exc, RecordsError)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
