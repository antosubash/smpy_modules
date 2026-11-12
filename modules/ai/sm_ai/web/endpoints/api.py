"""REST API for AI settings. Everything requires ai.manage."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from simple_module_hosting.permissions import RequiresPermission

from sm_ai.contracts.schemas import (
    AiModelsResult,
    AiSettingsOut,
    AiSettingsUpdate,
    AiTestRequest,
    AiTestResult,
)
from sm_ai.core import constants, services
from sm_ai.web import probe_errors
from sm_ai.web.deps import AiServiceDep, can_edit_settings
from sm_ai.web.service import AiService

router = APIRouter()

_MANAGE = Depends(RequiresPermission(constants.PERM_MANAGE))


@router.get("/settings", response_model=AiSettingsOut, dependencies=[_MANAGE])
async def get_settings() -> AiSettingsOut:
    # No AiServiceDep: current() only reads the module-global holder, and the
    # dependency would open a DB session the read never touches.
    return AiService.current()


@router.put("/settings", response_model=AiSettingsOut, dependencies=[_MANAGE])
async def update_settings(
    data: AiSettingsUpdate, request: Request, service: AiServiceDep
) -> AiSettingsOut:
    changes = AiService.build_changes(data)
    # The page always sends the switch. An unchanged value is dropped here,
    # before any await, so it is never written back: a save racing an admin who
    # just turned it off cannot restore the stale value without settings.edit.
    AiService.drop_unchanged_policy(changes)
    if not changes:
        return service.current()
    if AiService.changes_network_policy(changes) and not await can_edit_settings(request):
        raise HTTPException(
            status_code=403, detail=f"Permission required: {constants.PERM_SETTINGS_EDIT}"
        )
    errors = AiService.slot_errors(changes) + await AiService.base_url_errors(changes)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return await service.apply(changes)


@router.post("/test", response_model=AiTestResult, dependencies=[_MANAGE])
async def test_connection(data: AiTestRequest) -> AiTestResult:
    """One tiny real call through the configured slot.

    The only place this module itself calls a provider. Every failure —
    missing config, unreadable key, refused or bad URL, auth error, timeout —
    comes back as ``ok: false`` with a stable ``code`` and a fixed message
    (``probe_errors``); a wrong URL is a result, not a 500.
    """
    from pydantic_ai import Agent

    from sm_ai.connections import resolve

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
    except Exception as exc:  # a failed probe is a result, not a bug
        return AiTestResult(model=label, **_failed("test probe", data.slot, exc))
    return AiTestResult(ok=True, model=label, latency_ms=int((time.monotonic() - started) * 1000))


@router.post("/models", response_model=AiModelsResult, dependencies=[_MANAGE])
async def list_models(data: AiTestRequest) -> AiModelsResult:
    """The model ids the slot's *saved* endpoint serves, for the model field.

    Same contract as the test probe: any failure is ``ok: false`` with a
    code, so a wrong URL or key reads as a result on the card.
    """
    from sm_ai.connections import discovery

    try:
        async with asyncio.timeout(constants.TEST_TIMEOUT_SECONDS):
            models = await discovery.list_models(services.current_settings(), data.slot)
    except Exception as exc:
        return AiModelsResult(**_failed("model listing", data.slot, exc))
    return AiModelsResult(
        ok=True,
        models=models[: discovery.MAX_MODELS],
        truncated=len(models) > discovery.MAX_MODELS,
    )


def _failed(what: str, slot: str, exc: Exception) -> dict[str, object]:
    code, message, status = probe_errors.probe_error(what, slot, exc)
    return {"ok": False, "error": message, "code": code, "status": status}
