"""Pinning over a real socket and a real TLS handshake (fixtures: ``conftest.py``).

A TLS server on 127.0.0.1 holds a certificate for ``cal.example`` only, signed by a throwaway
CA. DNS says ``cal.example`` (and ``wrong.example``) is 127.0.0.1, and the guard's address rule is
widened to 127.0.0.1 inside these tests alone. The transport must dial the pinned IP, send SNI and
Host for the name, and verify the certificate against the name, so the wrong name fails.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
from sm_events.feeds.subscriptions import client, policy
from sm_events.feeds.subscriptions.url_safety import UnsafeURLError

from tests.feeds.subscriptions.conftest import ICS

ON = policy.Policy(
    allow_private=True, may_use_private=True
)  # any port: the test server's is random


async def _get(transport: client.PinnedTransport, url: str) -> bytes:
    response = await transport.handle_async_request(httpx.Request("GET", url))
    try:
        return await response.aread()
    finally:
        await response.aclose()


async def test_pinned_tls_request_keeps_sni_host_and_verifies_the_name(tls_server):
    port, seen = tls_server
    transport = client.PinnedTransport(ON)
    try:
        assert await _get(transport, f"https://cal.example:{port}/feed.ics") == ICS
    finally:
        await transport.aclose()
    assert seen["sni"] == "cal.example"
    assert seen["host"] == f"cal.example:{port}"
    assert seen["requests"] == ["GET /feed.ics HTTP/1.1"]


async def test_certificate_is_checked_against_the_hostname_not_the_ip(tls_server):
    port, _ = tls_server
    transport = client.PinnedTransport(ON)
    try:
        with pytest.raises(httpx.ConnectError, match=r"(?i)certificate|hostname"):
            await _get(transport, f"https://wrong.example:{port}/feed.ics")
    finally:
        await transport.aclose()


async def test_the_guard_is_not_widened_outside_the_override(tls_server, monkeypatch):
    """Without the test's widening, loopback is refused before any socket is opened."""
    port, seen = tls_server
    monkeypatch.setattr(policy, "address_allowed", seen["real"])  # the real rule again
    transport = client.PinnedTransport(ON)
    with pytest.raises(UnsafeURLError) as caught:
        await _get(transport, f"https://cal.example:{port}/feed.ics")
    assert caught.value.code == "non_public_address"
    assert "sni" not in seen


async def test_each_name_is_verified_on_its_own_connection(tls_server):
    """No keep-alive: two requests, two handshakes; a name verified once is never trusted for
    another name on the same IP."""
    port, seen = tls_server
    transport = client.PinnedTransport(ON)
    try:
        for _ in range(2):
            assert await _get(transport, f"https://cal.example:{port}/a") == ICS
        assert seen["connections"] == 2
        with pytest.raises(httpx.ConnectError):
            await _get(transport, f"https://wrong.example:{port}/a")
    finally:
        await transport.aclose()


async def test_cancel_mid_handshake_closes_the_socket(stalling_server):
    port, events = stalling_server
    transport = client.PinnedTransport(ON)
    task = asyncio.ensure_future(_get(transport, f"https://stall.example:{port}/a.ics"))
    await asyncio.wait_for(events["accepted"].wait(), 2)
    await asyncio.sleep(0.05)  # the ClientHello is out; the handshake is waiting
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(events["eof"].wait(), 1)
    await transport.aclose()


async def test_deadline_mid_handshake_closes_the_socket(stalling_server):
    """A deadline (``asyncio.timeout``) is a cancellation too."""
    port, events = stalling_server
    transport = client.PinnedTransport(ON)
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.3):
            await _get(transport, f"https://stall.example:{port}/a.ics")
    await asyncio.wait_for(events["eof"].wait(), 1)
    await transport.aclose()
