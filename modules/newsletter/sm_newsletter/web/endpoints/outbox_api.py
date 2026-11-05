"""The console transport's capture, for development and e2e: ``GET /outbox``."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from simple_module_hosting.permissions import RequiresPermission

from sm_newsletter.core import constants
from sm_newsletter.core.errors import OutboxUnavailable
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.sending.transport.console import captured
from sm_newsletter.web.schemas.outbox import OutboxMessage

router = APIRouter(
    dependencies=[Depends(bind_admin), Depends(RequiresPermission(constants.PERM_MANAGE))]
)


@router.get("/outbox", response_model=list[OutboxMessage])
async def list_outbox(request: Request, tenant: str = Depends(bind_admin)) -> list[OutboxMessage]:
    if request.app.state.sm_newsletter.settings.transport != "console":
        raise OutboxUnavailable()
    return [
        OutboxMessage(
            to=m.to, subject=m.subject, html=m.html, text=m.text, headers=m.headers, at=m.at
        )
        for m in captured(tenant)
    ]
