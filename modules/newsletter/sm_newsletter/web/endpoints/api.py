"""The admin JSON API, mounted under ``ROUTE_PREFIX_API``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import RequiresPermission
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import constants
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.web import settings_service
from sm_newsletter.web.schemas import SmtpPasswordOut, SmtpPasswordUpdate

# ``bind_admin`` first: yield dependencies exit in reverse, and ``get_db``'s
# commit (opened by the handler) has to happen while the tenant is still bound.
router = APIRouter(
    prefix="/settings",
    dependencies=[Depends(bind_admin), Depends(RequiresPermission(constants.PERM_MANAGE))],
)


@router.put("/smtp-password", response_model=SmtpPasswordOut)
async def put_smtp_password(
    body: SmtpPasswordUpdate, request: Request, db: AsyncSession = Depends(get_db)
) -> SmtpPasswordOut:
    stored = await settings_service.set_smtp_password(request.app, db, body.password)
    return SmtpPasswordOut(has_password=stored)
