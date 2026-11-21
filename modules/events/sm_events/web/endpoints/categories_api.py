"""``/api/events/categories``: a tenant-wide label with a name per language.

Anyone with ``events.view`` may list them; writes need ``events.manage``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from simple_module_db.deps import get_db

from sm_events.calendar import categories as service
from sm_events.web.endpoints.deps import get_settings, require_manage, require_view
from sm_events.web.schemas.categories import CategoryCreate, CategoryOut, CategoryPatch

router = APIRouter(prefix="/categories", tags=["categories"], dependencies=[require_view])


def _locales(request: Request) -> tuple[str, ...]:
    return tuple(get_settings(request).content_locales)


@router.get("")
async def list_categories(db=Depends(get_db)) -> list[CategoryOut]:
    return [CategoryOut.model_validate(c) for c in await service.list_categories(db)]


@router.post("", status_code=201, dependencies=[require_manage])
async def create_category(
    body: CategoryCreate, request: Request, db=Depends(get_db)
) -> CategoryOut:
    row = await service.create_category(db, body, locales=_locales(request))
    return CategoryOut.model_validate(row)


@router.patch("/{category_id}", dependencies=[require_manage])
async def update_category(
    category_id: uuid.UUID, body: CategoryPatch, request: Request, db=Depends(get_db)
) -> CategoryOut:
    row = await service.get_category(db, category_id)
    row = await service.update_category(db, row, body, locales=_locales(request))
    return CategoryOut.model_validate(row)


@router.delete("/{category_id}", status_code=204, dependencies=[require_manage])
async def delete_category(category_id: uuid.UUID, db=Depends(get_db)) -> Response:
    await service.delete_category(db, await service.get_category(db, category_id))
    return Response(status_code=204)
