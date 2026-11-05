"""The admin JSON API, mounted under ``ROUTE_PREFIX_API``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Request
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import RequiresPermission
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import constants
from sm_newsletter.core.errors import InvalidPassword, InvalidSettings
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.web.schemas.campaigns import parse_payload
from sm_newsletter.web.schemas.settings import (
    SettingsOut,
    SettingsSaved,
    SettingsUpdate,
    SmtpPasswordOut,
    SmtpPasswordUpdate,
)
from sm_newsletter.web.services import settings as settings_service

MAX_PASSWORD_LEN = 1024

# ``bind_admin`` first: yield dependencies exit in reverse, and ``get_db``'s
# commit (opened by the handler) has to happen while the tenant is still bound.
router = APIRouter(
    prefix="/settings",
    dependencies=[
        Depends(bind_admin),
        Depends(RequiresPermission(constants.PERM_MANAGE)),
    ],
)

# As strict as the generic Settings write the writes below replace.
_EDIT = [Depends(RequiresPermission(constants.PERM_SETTINGS_EDIT))]


@router.get("", response_model=SettingsOut)
async def get_settings(request: Request) -> SettingsOut:
    return settings_service.read_settings(request.app)


@router.put("", response_model=SettingsSaved, dependencies=_EDIT)
async def put_settings(
    request: Request, payload: Any = Body(...), db: AsyncSession = Depends(get_db)
) -> SettingsSaved:
    # Unparsed body + parse_payload: FastAPI's own 422 would echo the input.
    body = parse_payload(SettingsUpdate, payload, error=InvalidSettings)
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    try:
        cleared = await settings_service.update_settings(request.app, db, changes)
    except ValueError:  # a merged value the model refuses; never echo it
        raise InvalidSettings() from None
    return SettingsSaved(
        **settings_service.read_settings(request.app).model_dump(), password_cleared=cleared
    )


@router.put("/smtp-password", response_model=SmtpPasswordOut, dependencies=_EDIT)
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
