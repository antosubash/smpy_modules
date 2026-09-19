"""Record Type CRUD endpoints — the schema half of the JSON API.

Mounted directly on ``ROUTE_PREFIX_API`` (``/api/records``), not under a
``/types`` sub-router with its own prefix: the paths below already spell
``/types`` and ``/types/{key}`` themselves, matching the contract in the
implementation plan exactly.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from sm_records.contracts.schemas import (
    TypeCreate,
    TypeListResponse,
    TypeRead,
    TypeUpdate,
    type_read,
)
from sm_records.deps import (
    actor,
    get_settings,
    load_type,
    request_db,
    require_manage_types,
    require_view,
)
from sm_records.endpoints.api._errors import RecordsErrorRoute
from sm_records.models import RecordType
from sm_records.services import types as type_service

router = APIRouter(route_class=RecordsErrorRoute)


@router.get("/types", response_model=TypeListResponse, dependencies=[require_view])
async def list_types(db: AsyncSession = Depends(request_db)) -> TypeListResponse:
    rtypes = await type_service.list_types(db)
    items = [type_read(rtype, *await type_service.record_counts(db, rtype)) for rtype in rtypes]
    return TypeListResponse(items=items)


@router.post(
    "/types", response_model=TypeRead, status_code=201, dependencies=[require_manage_types]
)
async def create_type(
    body: TypeCreate,
    db: AsyncSession = Depends(request_db),
    settings=Depends(get_settings),
    who: str | None = Depends(actor),
) -> TypeRead:
    rtype = await type_service.create_type(
        db,
        key=body.key,
        label=body.label,
        settings=settings,
        label_plural=body.label_plural,
        description=body.description,
        icon=body.icon,
        fields_raw=body.fields,
        display_field=body.display_field,
        slug_field=body.slug_field,
        is_public=body.is_public,
        allowed_roles=body.allowed_roles,
        actor=who,
    )
    # A freshly created type holds no records, trashed or otherwise — skip
    # the queries rather than count a table it cannot yet appear in.
    return type_read(rtype, 0, 0)


@router.get("/types/{key}", response_model=TypeRead, dependencies=[require_view])
async def read_type(
    rtype: RecordType = Depends(load_type), db: AsyncSession = Depends(request_db)
) -> TypeRead:
    return type_read(rtype, *await type_service.record_counts(db, rtype))


@router.put("/types/{key}", response_model=TypeRead, dependencies=[require_manage_types])
async def update_type(
    body: TypeUpdate,
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
    settings=Depends(get_settings),
    who: str | None = Depends(actor),
) -> TypeRead:
    # Only what the caller actually sent — ``exclude_unset`` and not merely
    # "not None", since ``None`` is a legitimate value for e.g. ``description``.
    changes = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    if "fields" in changes:
        changes["fields_raw"] = changes.pop("fields")
    updated = await type_service.update_type(
        db, rtype, expected_version=body.expected_version, settings=settings, actor=who, **changes
    )
    return type_read(updated, *await type_service.record_counts(db, updated))


@router.delete("/types/{key}", status_code=204, dependencies=[require_manage_types])
async def delete_type(
    confirm_record_count: int = Query(...),
    rtype: RecordType = Depends(load_type),
    db: AsyncSession = Depends(request_db),
) -> None:
    await type_service.delete_type(db, rtype, confirm_record_count=confirm_record_count)
