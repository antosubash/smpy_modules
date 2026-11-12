"""List the models a configured slot's endpoint serves.

Through the SDK each provider's pydantic-ai extra already installs, so this
adds no dependency. Reads the *saved* slot — the same rule as the test probe:
an unsaved key never leaves the browser for an endpoint nobody has saved.

A base URL goes through the same guard as a model call (#347): each SDK client
gets ``base_url.http_client_for``'s pinned client, closed after the listing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sm_ai.connections import base_url as guard
from sm_ai.connections import resolve
from sm_ai.core import constants

if TYPE_CHECKING:
    import httpx2

    from sm_ai.core.settings import AiSettings

MAX_MODELS = 500
"""A cap on what one response carries: OpenRouter-style gateways list
thousands, and a datalist that long helps nobody."""

_GOOGLE_PREFIX = "models/"
# Google tags each model with what it can do; the chat slot calls
# generateContent and the embedding slot embedContent.
_GOOGLE_ACTION = {
    constants.SLOT_CHAT: "generateContent",
    constants.SLOT_EMBEDDING: "embedContent",
}


async def list_models(settings: AiSettings, slot: str) -> list[str]:
    """Model ids for ``slot``, sorted and de-duplicated — every one of them.

    The endpoint applies ``MAX_MODELS`` so it can say that it did.

    Raises ``AiNotConfiguredError`` for a slot that cannot be reached at all
    (no provider, no key, no URL) and whatever the SDK raises for a failed call
    — the endpoint turns both into an ``ok: false`` result.
    """
    allowed = (
        constants.CHAT_PROVIDERS if slot == constants.SLOT_CHAT else constants.EMBEDDING_PROVIDERS
    )
    provider_id, _, key, base_url = resolve.slot_inputs(
        settings, slot, allowed, require_model=False
    )
    http = guard.http_client_for(settings, slot, base_url)
    try:
        if provider_id in (constants.PROVIDER_OPENAI, constants.PROVIDER_OPENAI_COMPATIBLE):
            names = await _openai(key, base_url, http)
        elif provider_id == constants.PROVIDER_ANTHROPIC:
            names = await _anthropic(key, base_url, http)
        elif provider_id == constants.PROVIDER_GOOGLE:
            names = await _google(key, base_url, _GOOGLE_ACTION[slot], http)
        else:  # slot_inputs admits only the providers above; a new one must say how it lists
            raise NotImplementedError(f"Model listing is not implemented for {provider_id!r}.")
    finally:
        if http is not None:
            await http.aclose()
    return sorted({name for name in names if name})


async def _openai(key: str, base_url: str, http: httpx2.AsyncClient | None) -> list[str]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=key, base_url=base_url or None, http_client=http)
    try:
        return [model.id async for model in client.models.list()]
    finally:
        await client.close()


async def _anthropic(key: str, base_url: str, http: httpx2.AsyncClient | None) -> list[str]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=key, base_url=base_url or None, http_client=http)
    try:
        return [model.id async for model in client.models.list(limit=1000)]
    finally:
        await client.close()


async def _google(
    key: str, base_url: str, action: str, http: httpx2.AsyncClient | None
) -> list[str]:
    from google import genai
    from google.genai import types

    options = types.HttpOptions(base_url=base_url, httpx_async_client=http) if base_url else None
    client = genai.Client(api_key=key, http_options=options)
    names: list[str] = []
    try:
        async for model in await client.aio.models.list():
            if action not in (model.supported_actions or []):
                continue
            # The API names models "models/gemini-…"; pydantic-ai takes the bare id.
            names.append((model.name or "").removeprefix(_GOOGLE_PREFIX))
    finally:
        await client.aio.aclose()
    return names
