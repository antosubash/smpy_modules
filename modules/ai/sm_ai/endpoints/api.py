"""REST API for AI settings. Everything requires ai.manage."""

from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, Depends
from simple_module_hosting.permissions import RequiresPermission

from sm_ai import constants, services
from sm_ai.contracts.errors import AiNotConfiguredError
from sm_ai.contracts.schemas import (
    AiModelsResult,
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
    except Exception as exc:  # a failed probe is a result, not a bug
        return AiTestResult(ok=False, model=label, error=_probe_error("test probe", data.slot, exc))
    return AiTestResult(
        ok=True, model=label, latency_ms=int((time.monotonic() - started) * 1000)
    )


@router.post("/models", response_model=AiModelsResult, dependencies=[_MANAGE])
async def list_models(data: AiTestRequest) -> AiModelsResult:
    """The model ids the slot's *saved* endpoint serves, for the model field.

    Same contract as the test probe: any failure is ``ok: false`` with the
    message, so a wrong URL or key reads as a result on the card.
    """
    from sm_ai import discovery

    try:
        async with asyncio.timeout(constants.TEST_TIMEOUT_SECONDS):
            models = await discovery.list_models(services.current_settings(), data.slot)
    except Exception as exc:
        return AiModelsResult(ok=False, error=_probe_error("model listing", data.slot, exc))
    return AiModelsResult(
        ok=True,
        models=models[: discovery.MAX_MODELS],
        truncated=len(models) > discovery.MAX_MODELS,
    )


def _probe_error(what: str, slot: str, exc: Exception) -> str:
    """The message a failed probe shows on the card, logged on the way.

    A timeout is our own deadline, not the provider's failure, so it is not
    logged at all.
    """
    if isinstance(exc, TimeoutError):
        return f"Timed out after {constants.TEST_TIMEOUT_SECONDS}s."
    _log_probe_failure(what, slot, exc)
    return str(exc) or type(exc).__name__


def _log_probe_failure(what: str, slot: str, exc: Exception) -> None:
    """One line for an expected failure, a traceback for anything else.

    An unreachable server, a refused key or a provider's error status is a
    configuration problem the card already shows; its stack frames are noise.
    Anything else may be a real defect — a pydantic-ai or SDK API change — and
    keeps the traceback, without which it would read like a config problem.
    """
    if isinstance(exc, (AiNotConfiguredError, *_provider_errors())):
        logger.warning("AI %s %s failed: %s", slot, what, exc)
    else:
        logger.warning("AI %s %s failed", slot, what, exc_info=exc)


def _provider_errors() -> tuple[type[BaseException], ...]:
    """Exception types that mean "the provider said no", imported lazily."""
    import httpx
    from anthropic import APIError as AnthropicError
    from google.genai.errors import APIError as GoogleError
    from openai import APIError as OpenAIError

    # ModelAPIError, not just ModelHTTPError: pydantic-ai wraps a refused
    # connection in the former, and that is the commonest failure of all.
    from pydantic_ai.exceptions import ModelAPIError

    return (httpx.HTTPError, OpenAIError, AnthropicError, GoogleError, ModelAPIError)
