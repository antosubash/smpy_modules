"""One shared HTTP client per loop and origin; no redirects in private mode (#347)."""

from __future__ import annotations

import asyncio

import httpx2
import pytest
from pydantic_ai import Agent
from sm_ai.connections import clients, discovery, resolve
from sm_ai.core import constants, crypto, services
from sm_ai.core.settings import AiSettings

SECRET = "test-secret-key-for-clients"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", SECRET)
    yield
    services.reset()


def _chat(url: str, **kw) -> AiSettings:
    return AiSettings(
        chat_provider=constants.PROVIDER_OPENAI_COMPATIBLE,
        chat_model="m",
        chat_base_url=url,
        chat_api_key=crypto.encrypt_value("sk-secret"),
        **kw,
    )


def _http_of(model) -> httpx2.AsyncClient:
    return model._provider.client._client  # AsyncOpenAI's httpx2 client


async def test_repeated_builds_on_one_loop_share_one_client():
    loop = asyncio.get_running_loop()
    settings = _chat("http://gw.example/v1")
    seen = {id(_http_of(resolve.build_chat_model(settings))) for _ in range(50)}
    assert len(seen) == 1
    assert clients.cached(loop) == 1


async def test_the_cache_is_bounded_per_loop():
    loop = asyncio.get_running_loop()
    for i in range(clients.MAX_PER_LOOP + 5):
        resolve.build_chat_model(_chat(f"http://gw{i}.example/v1"))
    assert clients.cached(loop) == clients.MAX_PER_LOOP


def test_with_no_running_loop_nothing_is_cached():
    settings = _chat("http://gw.example/v1")
    first, second = (_http_of(resolve.build_chat_model(settings)) for _ in range(2))
    assert first is not second


def test_each_loop_gets_its_own_client():
    settings = _chat("http://gw.example/v1")

    async def build():
        return _http_of(resolve.build_chat_model(settings))

    assert asyncio.run(build()) is not asyncio.run(build())


async def test_with_private_urls_allowed_a_redirect_is_not_followed(monkeypatch):
    seen: list[httpx2.Request] = []

    def handler(request):
        seen.append(request)
        return httpx2.Response(302, headers={"location": "http://elsewhere.example/steal"})

    monkeypatch.setattr(clients, "_private_transport", lambda: httpx2.MockTransport(handler))
    settings = _chat("http://127.0.0.1:9/v1", allow_private_base_url=True)
    model = resolve.build_chat_model(settings, max_retries=0)
    with pytest.raises(Exception):  # noqa: B017 - the SDK's own error for a 3xx
        await Agent(model).run("hi")
    assert [r.url.host for r in seen] == ["127.0.0.1"]


async def test_discovery_closes_the_client_it_opens(monkeypatch):
    opened = []

    async def fake(key, base_url, http):
        opened.append(http)
        return ["m"]

    monkeypatch.setattr(discovery, "_openai", fake)
    loop = asyncio.get_running_loop()
    before = clients.cached(loop)
    await discovery.list_models(_chat("http://127.0.0.1:9/v1", allow_private_base_url=True), "chat")
    [http] = opened
    assert http.is_closed
    assert clients.cached(loop) == before  # unshared: not in the loop's cache
