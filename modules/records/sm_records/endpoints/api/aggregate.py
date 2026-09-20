"""``GET /types/{key}/records/aggregate`` — Phase 5 §5.1.

One endpoint, two readings. Without ``?reduce=`` it is a live ``GROUP BY``
over the map index tables, always available and never stored. With it, it
returns the maintained rows of a reduce index. The shape is the same either
way, so a caller can ask both and compare — which is how drift in a
maintained aggregate is noticed by the thing that reads it, rather than only
by an operator who happened to run the verifier.

**Not on the public API, and it never will be.** ``records.view`` plus the
type's ``allowed_roles`` (``load_allowed_type``) gate it exactly as they gate
the record list. An anonymous aggregate is an oracle over rows the caller
cannot read: ``group_by=status`` on a type whose drafts are private tells an
unauthenticated reader how many drafts exist, and a ``min``/``max`` over a
date field, asked repeatedly under different filters, reconstructs individual
values a row at a time. The anonymous read API (§10) serves published
documents and answers no questions *about* them.

Mounted before ``records.router`` (see ``endpoints/api/__init__``): Starlette
matches in registration order, and ``/types/{key}/records/{uuid}`` would
otherwise swallow this as a record whose uuid is "aggregate".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records import constants
from sm_records.contracts.aggregate import AggregateResponse
from sm_records.deps import (
    get_settings,
    load_allowed_type,
    parse_filters,
    request_db,
    require_view,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.index.aggregate import parse_metric
from sm_records.index.query import Filter, FilterOp, QueryError
from sm_records.models import RecordType
from sm_records.services import aggregate as aggregate_service
from sm_records.settings import RecordsSettings

router = APIRouter(prefix="/types/{key}", route_class=RecordsErrorRoute)


@router.get("/records/aggregate", response_model=AggregateResponse, dependencies=[require_view])
async def aggregate_records(
    rtype: RecordType = Depends(load_allowed_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    group_by: str | None = Query(default=None),
    metric: str | None = Query(default=None),
    filters: list[Filter] = Depends(parse_filters),
    locale: str | None = Query(default=None, alias=constants.LOCALE_PARAM),
    reduce: str | None = Query(default=None),
) -> AggregateResponse:
    """Counts per group, from the index tables or from a reduce index.

    ``group_by`` is an indexed field of the type, a virtual field an index
    provider projects, or a fixed column (``status``, ``locale``, ``slug``,
    ``position``, ``published_at``, …). It is resolved through the *same*
    function the filter grammar resolves a field with, so a key the type does
    not declare is a 400, one that is declared but not indexed is a 400, and
    one that is mid-rebuild is a 409 — identical to filtering on it.

    ``metric`` is ``count`` (the default), ``sum:<number field>`` or
    ``min:<field>``/``max:<field>`` over a number, date, datetime or text
    field. ``sum`` is refused over a multi-valued field: the join would add
    each record's value once per value it holds.

    ``filter=`` repeats and means exactly what it means on the list, including
    the soft-delete rule — the trash is never counted. ``locale=`` is the
    fixed-column filter spelled as a parameter, because "this language" is the
    question a content dashboard asks most.

    ``reduce=<key>`` reads the maintained rows of a registered reduce spec
    instead. Those rows are a fold of the whole type and cannot be narrowed
    after the fact, so combining it with ``group_by``, ``metric``, ``filter``
    or ``locale`` is a 400 rather than a filter silently ignored.

    **A multi-valued ``group_by`` counts a record once per value it holds**, so
    the group counts sum to more than the number of records — the same reading
    ``filter=tags:eq:a`` has, and the only honest one for "records per tag".
    """
    if reduce is not None:
        if group_by or metric or filters or locale:
            raise QueryError(
                "reduce",
                "unsupported_op",
                "a maintained aggregate is a fold of the whole type: it cannot be combined "
                "with group_by, metric, filter or locale — drop ?reduce= for a live one",
            )
        return await aggregate_service.stored_aggregate(db, rtype, settings=settings, key=reduce)
    if not group_by:
        raise QueryError("group_by", "unknown", "group_by is required (or pass ?reduce=<key>)")
    terms = list(filters)
    if locale is not None:
        terms.append(Filter(field=constants.LOCALE_PARAM, op=FilterOp.EQ, value=locale))
    return await aggregate_service.aggregate(
        db,
        rtype,
        settings=settings,
        group_by=group_by,
        metric=parse_metric(metric),
        filters=terms,
    )
