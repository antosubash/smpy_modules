"""Exception mapping shared by every Records API (and view) route.

FastAPI's ``exception_handler`` lives on the app, and this module owns only
``endpoints/**`` — not ``module.py``, so there is no hook here to register one
against. A custom :class:`~fastapi.routing.APIRoute` gets the same effect
scoped to exactly the routers built in this package: every
:class:`~sm_records.services.errors.RecordsError` (and the query grammar's
:class:`~sm_records.index.query.QueryError`) raised inside a handler becomes
the JSON shape the API contract promises, with no per-endpoint try/except to
keep in sync across a dozen routes.

``Conflict.current`` is the one case that needs more than the exception's own
attributes: it holds the ORM row a stale write collided with, and the
contract wants it serialised as a ``RecordRead`` or ``TypeRead``. That read
runs on a fresh, short-lived session rather than the request's own — by the
time this wrapper sees the exception, ``get_db`` has already rolled the
request's session back, so its identity map is not something to build a
response from.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from sm_records.contracts.schemas import record_read, type_read
from sm_records.index.query import QueryError
from sm_records.models import Record, RecordType
from sm_records.services.errors import Conflict, RecordsError, ReferencedByOthers, ValidationFailed
from sm_records.services.types import get_type_by_id, record_count

__all__ = ["RecordsErrorRoute"]


async def _current_dto(db: Any, current: Any) -> Any:
    if isinstance(current, RecordType):
        held = await record_count(db, current)
        return type_read(current, held).model_dump(mode="json")
    if isinstance(current, Record):
        rtype = await get_type_by_id(db, current.type_id)
        return record_read(rtype, current).model_dump(mode="json")
    return current


class RecordsErrorRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def wrapped(request: Request) -> Response:
            try:
                return await handler(request)
            except ValidationFailed as exc:
                return JSONResponse(
                    {"detail": exc.detail, "errors": exc.errors}, status_code=exc.status_code
                )
            except ReferencedByOthers as exc:
                return JSONResponse(
                    {"detail": exc.detail, "referrers": exc.referrers}, status_code=exc.status_code
                )
            except Conflict as exc:
                body: dict[str, Any] = {"detail": exc.detail}
                if exc.current is not None:
                    session = request.app.state.sm.db.session_factory()
                    try:
                        body["current"] = await _current_dto(session, exc.current)
                    finally:
                        await session.close()
                return JSONResponse(body, status_code=exc.status_code)
            except QueryError as exc:
                status = 409 if exc.reason == "reindexing" else 400
                return JSONResponse(
                    {"detail": str(exc), "field": exc.field, "reason": exc.reason},
                    status_code=status,
                )
            except RecordsError as exc:
                return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

        return wrapped
