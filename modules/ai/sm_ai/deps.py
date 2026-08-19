"""FastAPI dependencies for the AI module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from simple_module_db.deps import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from sm_ai.service import AiService


async def get_ai_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AiService:
    return AiService(request.app, db)


AiServiceDep = Annotated[AiService, Depends(get_ai_service)]
