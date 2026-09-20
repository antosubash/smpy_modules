"""The anonymous read API (design §10), mounted at ``public_route_prefix``.

**No authentication dependency anywhere in this module, and no read of
``request.state.user``.** That is the point of it: these two routes answer a
caller with no session, and the prefix is exempted from ``AuthMiddleware`` by
:mod:`sm_records.boot`. Anything that needed to know who was asking would
belong on the admin API instead.

Mounted from ``on_startup`` rather than ``register_routes`` because the prefix
is a database-backed setting, hydrated at lifespan start — see
:mod:`sm_records.boot` for why that is both necessary and safe.

Two rules the handlers exist to enforce, beyond what the services do:

* **Every refusal is the same 404.** ``services.public`` raises ``NotFound``
  with one body for a missing type, a private type, a draft and a trashed row
  alike, and ``RecordsErrorRoute`` renders it — so the endpoint adds no
  message of its own that could tell them apart.
* **Every bad filter or sort is a 400 naming the field.** The admin API
  answers 409 while a field is mid-reindex (§8.5); §10 refuses to reuse that
  here, because the difference between "cannot" and "cannot right now" is
  operational state an anonymous caller has no business seeing. So
  ``QueryError`` is caught and flattened, reason and all.

``HEAD`` is declared explicitly, from the same ``PUBLIC_ROUTE_METHODS`` the
exemption is pinned to. Starlette's own ``Route`` adds ``HEAD`` to every
``GET``, but FastAPI's ``APIRoute`` takes the method set verbatim — so a bare
``@router.get`` answers a link checker or a conditional GET with a 405 while
the auth exemption cheerfully allows it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import constants
from sm_records.contracts.public import (
    PublicRecordPage,
    PublicRecordRead,
    public_record_read,
    public_records_read,
)
from sm_records.deps import (
    PageCursor,
    get_settings,
    parse_cursor,
    parse_filters,
    parse_sorts,
    request_db,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.index.query import CursorError, Filter, QueryError, Sort
from sm_records.services import public as public_service
from sm_records.settings import RecordsSettings

router = APIRouter(route_class=RecordsErrorRoute)

_Handler = TypeVar("_Handler", bound=Callable[..., Any])


def _refused(exc: QueryError) -> HTTPException:
    """A filter or sort this surface will not answer, flattened to one 400.

    ``exc.reason`` is deliberately dropped: ``unknown``, ``not_indexed`` and
    ``reindexing`` are the same sentence to a caller who cannot see the schema,
    and the last of them is a running operation (§10).
    """
    return HTTPException(status_code=400, detail=f"cannot filter or sort by {exc.field!r}")


_READ = sorted(constants.PUBLIC_ROUTE_METHODS)
"""``["GET", "HEAD"]`` — the router and the auth exemption read one constant,
so a verb cannot be answered here and refused there (or the reverse)."""


def _read_route(path: str, **kwargs: Any) -> Callable[[_Handler], _Handler]:
    """Register one handler at ``path`` under every verb in ``_READ``.

    **One route per verb, not one route with two verbs.** FastAPI derives an
    ``operationId`` from the route's name and path and appends the method, but
    it does so per *operation* from a single ``APIRoute`` — so a route
    declaring ``GET`` and ``HEAD`` together emits two operations with the same
    id, warns twice when the schema is built, and breaks any generated client
    for this API. A route each, with the id spelled out, keeps the one
    constant above as the single source of the verb list.
    """

    def decorate(func: _Handler) -> _Handler:
        for method in _READ:
            router.api_route(
                path,
                methods=[method],
                operation_id=f"{func.__name__}_{method.lower()}",
                **kwargs,
            )(func)
        return func

    return decorate


@_read_route("/{type_key}", response_model=PublicRecordPage)
async def list_public_records(
    type_key: str,
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    page: int = Query(default=1, ge=1),
    page_size: int | None = Query(default=None, ge=1),
    cursor: PageCursor = Depends(parse_cursor),
    filters: list[Filter] = Depends(parse_filters),
    sorts: list[Sort] = Depends(parse_sorts),
) -> PublicRecordPage:
    """Published records of a public type, with the admin filter/sort grammar.

    ``page_size`` is clamped to ``max_page_size`` rather than refused, and no
    other parameter is declared beyond the pagination ones: ``expand`` and
    ``trashed`` are not options here, so they arrive as unknown query
    parameters and are ignored, which is what a query string a caller copied
    from the admin UI should do.

    ``?after=`` and ``?total=false`` are the same contract the admin listing
    has (F11, F4) — an anonymous client walking a large public type is
    precisely the caller that should not be paying for an ``OFFSET`` and a
    count it never reads. A cursor this listing cannot resume from is the same
    flat 400 a refused filter is.
    """
    rtype = await public_service.get_public_type(db, type_key)
    try:
        result = await public_service.list_public_records(
            db,
            rtype,
            settings=settings,
            filters=filters,
            sorts=sorts,
            page=page,
            page_size=page_size,
            after=cursor.after,
            with_total=cursor.with_total,
        )
    except QueryError as exc:
        raise _refused(exc) from exc
    except CursorError as exc:
        raise HTTPException(status_code=400, detail="cannot resume from that cursor") from exc
    return PublicRecordPage(
        items=public_records_read(rtype, result.items),
        total=result.total,
        total_capped=result.total_capped,
        next_cursor=result.next_cursor,
        page=page,
        page_size=settings.clamp_page_size(page_size),
    )


@_read_route("/{type_key}/{uuid}", response_model=PublicRecordRead)
async def get_public_record(
    type_key: str, uuid: str, db: AsyncSession = Depends(request_db)
) -> PublicRecordRead:
    """One published record. A draft, a trashed row, an unknown uuid and a
    private type are one and the same 404 (``services.public.NOT_FOUND``)."""
    rtype = await public_service.get_public_type(db, type_key)
    record = await public_service.get_public_record(db, rtype, uuid)
    return public_record_read(rtype, record)


__all__ = ["router"]
