"""The console transport's capture, for development and e2e: ``GET /outbox``."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from simple_module_hosting.permissions import RequiresPermission

from sm_newsletter.core import constants
from sm_newsletter.core.errors import OutboxUnavailable
from sm_newsletter.core.tenancy import bind_admin
from sm_newsletter.imports.launch import celery_eager
from sm_newsletter.sending.runtime import tick_in_app
from sm_newsletter.sending.transport.console import captured
from sm_newsletter.web.schemas.outbox import OutboxMessage

DISPATCH_ENVIRONMENTS = frozenset({"development", "testing"})

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


class TickOut(BaseModel):
    started: int
    spent: int
    finished: int
    stopped: str | None


def dispatch_hook_enabled(app: Any) -> bool:
    """The hook exists only on the console transport, with Celery eager, in a
    development or testing host (R17); a host without an environment is not one."""
    environment = getattr(app.state.sm.settings, "environment", None)
    return (
        app.state.sm_newsletter.settings.transport == "console"
        and celery_eager()
        and environment in DISPATCH_ENVIRONMENTS
    )


@router.post("/outbox/dispatch", response_model=TickOut)
async def dispatch_now(request: Request) -> TickOut:
    """Run one dispatcher tick here: the e2e server has no beat to send a campaign."""
    if not dispatch_hook_enabled(request.app):
        raise OutboxUnavailable()
    summary = await tick_in_app(request.app)
    return TickOut(
        started=summary.started,
        spent=summary.spent,
        finished=summary.finished,
        stopped=summary.stopped,
    )
