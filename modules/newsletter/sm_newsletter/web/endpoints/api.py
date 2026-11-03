"""The admin JSON API, mounted under ``ROUTE_PREFIX_API``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import RequiresPermission
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import constants
from sm_newsletter.core.errors import InvalidPassword
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.web import settings_service
from sm_newsletter.web.schemas import SmtpPasswordOut, SmtpPasswordUpdate

MAX_PASSWORD_LEN = 1024

# ``bind_admin`` first: yield dependencies exit in reverse, and ``get_db``'s
# commit (opened by the handler) has to happen while the tenant is still bound.
router = APIRouter(
    prefix="/settings",
    dependencies=[
        Depends(bind_admin),
        Depends(RequiresPermission(constants.PERM_MANAGE)),
        # As strict as the generic Settings write this endpoint replaces.
        Depends(RequiresPermission(constants.PERM_SETTINGS_EDIT)),
    ],
)


@router.put("/smtp-password", response_model=SmtpPasswordOut)
async def put_smtp_password(
    body: SmtpPasswordUpdate, request: Request, db: AsyncSession = Depends(get_db)
) -> SmtpPasswordOut:
    # Stored exactly as submitted: surrounding whitespace can be part of a
    # password. Only an empty / all-whitespace or oversized value is refused.
    password = body.password
    if not password.strip() or len(password) > MAX_PASSWORD_LEN:
        raise InvalidPassword()
    await settings_service.set_smtp_password(request.app, db, password)
    return SmtpPasswordOut(
        has_password=bool(request.app.state.sm_newsletter.settings.smtp_password)
    )
