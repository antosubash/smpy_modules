"""One shared HTTP client per loop and origin; no redirects in private mode (#347)."""

from __future__ import annotations

import asyncio
import gc
import weakref

import httpx2
import pytest
from pydantic_ai import Agent
from sm_ai.connections import clients, resolve
from sm_ai.core import constants, crypto
from sm_ai.core.settings import AiSettings


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


async def _ok_server():
    """A local HTTP/1.1 server that keeps each connection open until the client
    closes it (so a pooled idle connection would stay alive)."""

    async def handle(reader, writer):
        while await reader.readuntil(b"\r\n\r\n"):
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
            await writer.drain()

    async def guarded(reader, writer):
        try:
            await handle(reader, writer)
        except (asyncio.IncompleteReadError, ConnectionError):
            writer.close()

    server = await asyncio.start_server(guarded, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


def test_a_finished_loop_is_freed_in_private_mode(monkeypatch):
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(var, raising=False)
    refs = []

    async def run():
        server, port = await _ok_server()
        url = f"http://127.0.0.1:{port}/v1"
        client = clients.client_for("private", url)
        assert (await client.get(f"{url}/models")).status_code == 200
        refs.append(weakref.ref(asyncio.get_running_loop()))
        server.close()

    asyncio.run(run())
    gc.collect()
    assert refs[0]() is None  # no idle connection kept the loop, or its entry, alive


async def test_a_closed_entry_does_not_evict_a_live_one():
    loop = asyncio.get_running_loop()
    urls = [f"http://gw{i}.example/v1" for i in range(clients.MAX_PER_LOOP)]
    first = [clients.client_for("pinned", u) for u in urls]
    await first[3].aclose()
    again = clients.client_for("pinned", urls[3])
    assert again is not first[3] and not again.is_closed
    assert clients.cached(loop) == clients.MAX_PER_LOOP
    assert clients.client_for("pinned", urls[0]) is first[0]  # still cached


async def test_evicting_a_client_mid_request_does_not_fail_it(monkeypatch):
    release = asyncio.Event()

    async def handler(request):
        await release.wait()
        return httpx2.Response(200, json={"ok": True})

    monkeypatch.setattr(clients, "_private_transport", lambda: httpx2.MockTransport(handler))
    busy = clients.client_for("private", "http://10.0.0.1/v1")
    pending = asyncio.create_task(busy.get("http://10.0.0.1/v1/models"))
    await asyncio.sleep(0)
    for i in range(clients.MAX_PER_LOOP):  # pushes the busy client out
        clients.client_for("private", f"http://10.0.1.{i}/v1")
    assert clients.client_for("private", "http://10.0.0.1/v1") is not busy
    release.set()
    assert (await pending).status_code == 200
    assert not busy.is_closed
