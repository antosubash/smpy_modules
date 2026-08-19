"""REST API for AI settings. Everything requires ai.manage."""

from __future__ import annotations

import asyncio
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

router = APIRouter()

_MANAGE = Depends(RequiresPermission(constants.PERM_MANAGE))


@router.get("/settings", response_model=AiSettingsOut, dependencies=[_MANAGE])
async def get_settings(service: AiServiceDep) -> AiSettingsOut:
    return service.current()


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

    from sm_ai import contracts

    started = time.monotonic()
    label = ""
    try:
        async with asyncio.timeout(constants.TEST_TIMEOUT_SECONDS):
            if data.slot == constants.SLOT_CHAT:
                label = services.current_settings().chat_model
                agent = Agent(contracts.resolve_model())
                await agent.run(constants.TEST_PROMPT)
            else:
                label = services.current_settings().embedding_model
                await contracts.resolve_embedder().embed_query(constants.TEST_PROMPT)
    except TimeoutError:
        return AiTestResult(
            ok=False,
            model=label,
            error=f"Timed out after {constants.TEST_TIMEOUT_SECONDS}s.",
        )
    except Exception as exc:  # noqa: BLE001 — a failed probe is a result, not a bug
        return AiTestResult(ok=False, model=label, error=str(exc) or type(exc).__name__)
    return AiTestResult(
        ok=True, model=label, latency_ms=int((time.monotonic() - started) * 1000)
    )
