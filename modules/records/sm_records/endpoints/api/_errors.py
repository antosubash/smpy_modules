"""Exception mapping shared by every Records API (and view) route.

FastAPI's ``exception_handler`` lives on the app, and this module owns only
``endpoints/**`` — not ``module.py``, so there is no hook here to register one
against. A custom :class:`~fastapi.routing.APIRoute` gets the same effect
scoped to exactly the routers built in this package: every
:class:`~sm_records.services.errors.RecordsError` (and the query grammar's
:class:`~sm_records.index.query.QueryError`) raised inside a handler becomes
the JSON shape the API contract promises, with no per-endpoint try/except to
keep in sync across a dozen routes.

**A caught exception is one the session never hears about, so the rollback is
ours to do.** Catching here means the handler returns a response rather than
raising, ``get_db`` resumes normally, finds the has-writes flag its
``after_flush`` listener set, and commits — so a refused delete that had
already nulled one referrer before meeting a ``restrict`` deeper down
committed that rewrite under a 409. Every error path below therefore rolls the
request's session back explicitly, and clears the flag so ``get_db``'s own
exit takes the read-only branch. The session is the one
:func:`sm_records.deps.request_db` parked on ``request.scope``.

``Conflict.current`` is the one case that needs more than the exception's own
attributes: it holds the ORM row a stale write collided with, and the
contract wants it serialised as a ``RecordRead`` or ``TypeRead``. That read
runs on a fresh, short-lived session rather than the request's own, and it
happens *before* the rollback — a rollback expires every instance in the
request's identity map, and refreshing one from async code outside a greenlet
is a ``MissingGreenlet``, not a response.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from sm_records.contracts.schema_change import dry_run_report_read
from sm_records.contracts.schemas import record_read, type_read
from sm_records.deps import request_session
from sm_records.index.query import QueryError
from sm_records.models import RecordType, table_sets
from sm_records.services._common import SESSION_HAS_WRITES_KEY
from sm_records.services.errors import (
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

__all__ = ["RecordsErrorRoute"]


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
        live, trashed = await record_counts(db, current)
        return type_read(current, live, trashed).model_dump(mode="json")
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


async def _response_for(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, ValidationFailed):
        return JSONResponse(
            {"detail": exc.detail, "errors": exc.errors}, status_code=exc.status_code
        )
    if isinstance(exc, ReferencedByOthers):
        return JSONResponse(
            {"detail": exc.detail, "referrers": exc.referrers}, status_code=exc.status_code
        )
    if isinstance(exc, SchemaChangeRefused):
        # Checked ahead of the generic ``Conflict`` branch below: this is one,
        # but its whole point is the dry-run report riding along with it
        # (design §8.2), not a ``current`` row to reload.
        report = dry_run_report_read(exc.report).model_dump(mode="json")
        return JSONResponse({"detail": exc.detail, "report": report}, status_code=exc.status_code)
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


async def _discard_writes(request: Request) -> None:
    """Undo whatever the refused call wrote before it refused.

    See the module docstring: without this the response says 409 and the
    request still commits.
    """
    session = request_session(request)
    if session is None:  # pragma: no cover - every route here uses ``request_db``
        return
    await session.rollback()
    session.info.pop(SESSION_HAS_WRITES_KEY, None)


class RecordsErrorRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def wrapped(request: Request) -> Response:
            try:
                return await handler(request)
            except (RecordsError, QueryError) as exc:
                response = await _response_for(request, exc)
                await _discard_writes(request)
                return response

        return wrapped
