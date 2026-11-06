"""``POST /lists``: create a subscription list (R11). ``GET /lists`` lives in campaigns_api."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import RequiresPermission
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import constants
from sm_newsletter.core.errors_import import InvalidListKey
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.imports.lists import create_list
from sm_newsletter.web.schemas.campaigns import parse_payload
from sm_newsletter.web.schemas.imports import ListCreate

router = APIRouter(dependencies=[Depends(bind_admin)])


@router.post(
    "/lists",
    status_code=201,
    dependencies=[Depends(RequiresPermission(constants.PERM_MANAGE))],
)
async def create(
    request: Request,
    payload: Any = Body(...),
    tenant: str = Depends(bind_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    data = parse_payload(ListCreate, payload, error=InvalidListKey)
    key = await create_list(request.app, db, tenant_id=tenant, key=data.key, label=data.label)
    return {"key": key}
