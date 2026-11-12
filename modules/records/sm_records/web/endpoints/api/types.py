"""Record Type CRUD endpoints — the schema half of the JSON API.

Mounted directly on ``ROUTE_PREFIX_API`` (``/api/records``), not under a
``/types`` sub-router with its own prefix: the paths below already spell
``/types`` and ``/types/{key}`` themselves, matching the contract in the
implementation plan exactly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.schemas import (
    TypeCreate,
    TypeListResponse,
    TypeRead,
    TypeUpdate,
    type_read,
)
from sm_records.core.settings import RecordsSettings
from sm_records.models import RecordType
from sm_records.records.services import types as type_service
from sm_records.records.services._access import role_blocked
from sm_records.records.services.errors import ValidationFailed
from sm_records.web.deps import (
    actor,
    caller_roles,
    check_type_roles,
    get_settings,
    load_schema_type,
    load_type,
    request_db,
    require_manage_types,
    require_view,
)
from sm_records.web.endpoints.api._errors import RecordsErrorRoute
from sm_records.web.endpoints.api._responses import TYPE_WRITE, responses
from sm_records.web.endpoints.api._type_writes import (
    _check_roles_for_discard,
    _defer_reindex,
    apply_update,
    create_from,
)
from sm_records.web.menu import mark_dirty

router = APIRouter(route_class=RecordsErrorRoute, responses=responses(*TYPE_WRITE))


@router.get("/types", response_model=TypeListResponse, dependencies=[require_view])
async def list_types(request: Request, db: AsyncSession = Depends(request_db)) -> TypeListResponse:
    """Every type this caller may read records of. One whose ``allowed_roles``
    exclude them is *omitted* rather than listed-and-then-403: every screen
    this feeds links straight to the type's record list, which
    ``deps.load_allowed_type`` refuses (§10). Reading one type by key is a
    different question — see :func:`read_type`."""
    return TypeListResponse(items=await visible_types(request, db))


async def visible_types(request: Request, db: AsyncSession) -> list[TypeRead]:
    """Every type the caller's roles do not exclude, with its counts — this
    listing and the hub screen (``views_types.type_list``)."""
    roles = caller_roles(request)
    rtypes = [
        rtype for rtype in await type_service.list_types(db) if not role_blocked(rtype, roles)
    ]
    return [type_read(rtype, *await type_service.record_counts(db, rtype)) for rtype in rtypes]


@router.post(
    "/types", response_model=TypeRead, status_code=201, dependencies=[require_manage_types]
)
async def create_type(
    body: TypeCreate,
    request: Request,
    db: AsyncSession = Depends(request_db),
    settings=Depends(get_settings),
    who: str | None = Depends(actor),
) -> TypeRead:
    return await create_from(request, db, body, settings, who)


@router.get("/types/{key}", response_model=TypeRead, dependencies=[require_view])
async def read_type(
    rtype: RecordType = Depends(load_schema_type), db: AsyncSession = Depends(request_db)
) -> TypeRead:
    """One type's definition, and how many records it holds.

    ``load_schema_type`` and not ``load_type``: ``records.manage_types``
    reads this whatever ``allowed_roles`` says — the README's one exception,
    and the same one the type editor makes — and everybody else meets the
    narrowing. The ``record_count``/``trashed_record_count`` on ``TypeRead``
    are why it cannot simply be ``records.view``: they are a live count of a
    type whose records, trash and referrers this caller is refused.
    """
    return type_read(rtype, *await type_service.record_counts(db, rtype))


@router.put("/types/{key}", response_model=TypeRead, dependencies=[require_manage_types])
async def update_type(
    body: TypeUpdate,
    request: Request,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings: RecordsSettings = Depends(get_settings),
    who: str | None = Depends(actor),
) -> TypeRead:
    # Only what the caller actually sent — ``exclude_unset`` and not merely
    # "not None", since ``None`` is a legitimate value for e.g. ``description``.
    # ``force``/``orphaned`` are read straight off ``body`` below: they are
    # §8.2/§8.8's retry knobs, not columns, so they never belong in ``changes``.
    _check_roles_for_discard(request, rtype, body.orphaned)
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version", "force", "orphaned"})
    # ``key`` is not a column ``update_type`` accepts, but it *is* a key
    # clients send back with the rest of the type they just read. Dropping it
    # silently (the SQLModel default before ``TypeUpdate`` declared it) let a
    # caller believe it had renamed a type and get a 200; a value that differs
    # from the path is refused instead, and one that matches is a no-op echo.
    sent_key = changes.pop("key", None)
    if sent_key is not None and sent_key != rtype.key:
        problem = "key is immutable — it is in URLs, the API and every relation target"
        raise ValidationFailed(problem, [{"field": "key", "message": problem}])
    if "fields" in changes:
        changes["fields_raw"] = changes.pop("fields")
    return await apply_update(request, db, rtype, body, changes, settings, who)


@router.delete("/types/{key}", status_code=204, dependencies=[require_manage_types])
async def delete_type(
    request: Request,
    confirm_record_count: int = Query(...),
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
) -> None:
    """``records.manage_types`` *and* the type's own ``allowed_roles``.

    Deleting a type purges every record it holds, trash included — the widest
    write in the module. A caller the list excludes is refused a single record
    write and has a cascade into this type downgraded to ``restrict``
    (``services.delete._lifecycle._role_blocked``); letting the same caller destroy all
    of it was the one gap in that rule, not a deliberate exception.
    """
    check_type_roles(request, rtype)
    await type_service.delete_type(db, rtype, confirm_record_count=confirm_record_count)
    # Its sidebar entry, if any, and its ``records.type.<key>`` both go.
    mark_dirty(request.app)


@router.post("/types/{key}/reindex", status_code=202, dependencies=[require_manage_types])
async def reindex_type(
    request: Request,
    rtype: RecordType = Depends(load_type),
    settings: RecordsSettings = Depends(get_settings),
) -> dict[str, bool]:
    """Manually kick a stuck reindex (§8.9's health check names it — this is
    the fix). Schedules unconditionally, whether or not anything is actually
    pending: the runner is idempotent (``run_pending`` is a no-op with
    nothing to do), and an operator pressing this button already believes
    something is stuck, so a silent no-op here for "there's nothing pending
    any more" would look like the button did nothing.
    """
    _defer_reindex(request, rtype, settings)
    return {"scheduled": True}
