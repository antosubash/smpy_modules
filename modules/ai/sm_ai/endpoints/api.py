"""REST API for AI settings. Everything requires ai.manage."""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, Depends
from simple_module_hosting.permissions import RequiresPermission

from sm_ai import constants, services
from sm_ai.contracts.schemas import (
    AiSettingsOut,
    AiSettingsUpdate,
    AiTestRequest,
    AiTestResult,
)
from sm_ai.deps import AiServiceDep
from sm_ai.service import AiService

logger = logging.getLogger(__name__)

router = APIRouter()

_MANAGE = Depends(RequiresPermission(constants.PERM_MANAGE))


@router.get("/settings", response_model=AiSettingsOut, dependencies=[_MANAGE])
async def get_settings() -> AiSettingsOut:
    # No AiServiceDep: current() only reads the module-global holder, and the
    # dependency would open a DB session the read never touches.
    return AiService.current()


@router.put("/settings", response_model=AiSettingsOut, dependencies=[_MANAGE])
async def update_settings(data: AiSettingsUpdate, service: AiServiceDep) -> AiSettingsOut:
    changes = AiService.build_changes(data)
    if not changes:
        return service.current()
    return await service.apply(changes)


@router.post("/test", response_model=AiTestResult, dependencies=[_MANAGE])
async def test_connection(data: AiTestRequest) -> AiTestResult:
    """One tiny real call through the configured slot.

    The only place this module itself calls a provider. Every failure —
    missing config, unreadable key, bad URL, auth error, timeout — comes back
    as ``ok: false`` with the message; a wrong URL is a result, not a 500.
    """
    from pydantic_ai import Agent

    from sm_ai import resolve

    started = time.monotonic()
    label = ""
    try:
        # One snapshot for both the label and the probe — a concurrent save
        # must not make the reported model describe a different configuration
        # than the one actually exercised.
        settings = services.current_settings()
        async with asyncio.timeout(constants.TEST_TIMEOUT_SECONDS):
            if data.slot == constants.SLOT_CHAT:
                label = settings.chat_model
                agent = Agent(resolve.build_chat_model(settings))
                await agent.run(constants.TEST_PROMPT)
            else:
                label = settings.embedding_model
                await resolve.build_embedder(settings).embed_query(constants.TEST_PROMPT)
    except TimeoutError:
        return AiTestResult(
            ok=False,
            model=label,
            error=f"Timed out after {constants.TEST_TIMEOUT_SECONDS}s.",
        )
    except Exception as exc:  # a failed probe is a result, not a bug
        # ... but log it server-side with the traceback: without this an
        # actual code defect (e.g. a pydantic-ai API change) is
        # indistinguishable from a config problem in the inline error string.
        logger.warning("AI %s test probe failed", data.slot, exc_info=exc)
        return AiTestResult(ok=False, model=label, error=str(exc) or type(exc).__name__)
    return AiTestResult(
        ok=True, model=label, latency_ms=int((time.monotonic() - started) * 1000)
    )
