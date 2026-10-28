"""``safe_stream``'s one absolute deadline and ``PinnedTransport``'s per-origin pools.

The deadline covers every phase of a hop: resolution (bounded on its own too,
because a cancelled resolver thread keeps running), connecting across the
addresses, waiting for headers and every body read. Expiry is always
:class:`FetchTimeoutError`. Timeouts here are real but tiny.
"""

from __future__ import annotations

import asyncio
import threading
import time

import httpx
import pytest
from sm_images.imports import fetch, url_safety
from sm_images.imports.fetch import FetchTimeoutError, PinnedTransport, safe_stream

from tests.fetch_support import OTHER_PUBLIC_IP, PUBLIC_IP


async def _fetch(url: str, timeout: float) -> bytes:
    stream = safe_stream(url, max_bytes=1_000_000, timeout=timeout)
    return b"".join([chunk async for chunk in stream])


async def _timed_out(url: str, timeout: float) -> float:
    started = time.monotonic()
    with pytest.raises(FetchTimeoutError):
        await _fetch(url, timeout)
    return time.monotonic() - started


@pytest.fixture
def stuck_dns(monkeypatch):
    """A resolver that hangs until the test ends."""
    release = threading.Event()

    def hang(*_a, **_k):
        release.wait(10)
        raise OSError("released")

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", hang)
    yield
    release.set()


@pytest.mark.usefixtures("stuck_dns")
async def test_slow_dns_counts_against_the_deadline():
    assert await _timed_out("http://cdn.example/a.jpg", 0.1) < 1


@pytest.mark.usefixtures("stuck_dns")
async def test_dns_has_its_own_bound(monkeypatch):
    monkeypatch.setattr(fetch, "DNS_TIMEOUT_SECONDS", 0.05)
    assert await _timed_out("http://cdn.example/a.jpg", 30) < 1


async def test_trickling_headers_are_cut_off(resolver, inner):
    resolver["cdn.example"] = [PUBLIC_IP]

    async def slow(request):
        await asyncio.sleep(2)
        return httpx.Response(200)

    inner(slow)
    assert await _timed_out("http://cdn.example/a.jpg", 0.1) < 1


async def test_slow_connects_across_addresses_share_one_deadline(resolver, inner):
    resolver["dual.example"] = [PUBLIC_IP, OTHER_PUBLIC_IP, "93.184.216.36", "93.184.216.37"]

    async def refuse_slowly(request):
        await asyncio.sleep(0.08)
        raise httpx.ConnectTimeout("slow", request=request)

    inner(refuse_slowly)
    assert await _timed_out("http://dual.example/a.jpg", 0.1) < 0.3


async def test_trickling_body_is_cut_off(resolver, inner):
    resolver["cdn.example"] = [PUBLIC_IP]

    async def trickle():
        yield b"a"
        await asyncio.sleep(2)
        yield b"b"

    inner(lambda r: httpx.Response(200, content=trickle()))
    assert await _timed_out("http://cdn.example/a.jpg", 0.1) < 1


async def test_at_most_four_addresses_are_tried_per_hop(resolver, inner):
    resolver["many.example"] = [f"93.184.216.{n}" for n in range(30, 37)]

    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    seen = inner(refuse)
    with pytest.raises(httpx.ConnectError):
        await _fetch("http://many.example/a.jpg", 5)
    assert len(seen) == fetch.MAX_ADDRESSES_PER_HOP == 4


async def test_one_transport_never_shares_a_pool_between_names(resolver):
    """Two names on one IP through one instance get separate connection layers,
    so a TLS connection made (and verified) for one name is never reused for the other."""
    resolver["a.example"] = [PUBLIC_IP]
    resolver["b.example"] = [PUBLIC_IP]
    made: list[list[str]] = []

    def factory() -> httpx.AsyncBaseTransport:
        hosts: list[str] = []
        made.append(hosts)

        def handler(request):
            hosts.append(request.headers["host"])
            return httpx.Response(200)

        return httpx.MockTransport(handler)

    async with httpx.AsyncClient(transport=PinnedTransport(inner=factory)) as client:
        for url in ("https://a.example/1", "https://b.example/1", "https://a.example/2"):
            assert (await client.get(url)).status_code == 200
    assert made == [["a.example", "a.example"], ["b.example"]]
