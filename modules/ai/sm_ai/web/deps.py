"""FastAPI dependencies for the AI module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from simple_module_core.permissions import grants
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import ensure_resolved_permissions
from sqlalchemy.ext.asyncio import AsyncSession

from sm_ai.core import constants
from sm_ai.web.service import AiService


async def get_ai_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AiService:
    return AiService(request.app, db)


async def can_edit_settings(request: Request) -> bool:
    """Whether the caller holds ``settings.edit`` (the private-endpoint switch, #347)."""
    return grants(await ensure_resolved_permissions(request), constants.PERM_SETTINGS_EDIT)


AiServiceDep = Annotated[AiService, Depends(get_ai_service)]
