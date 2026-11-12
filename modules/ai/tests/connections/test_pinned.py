"""The pinned client: every request is resolved, validated and dialled by address (#347)."""

from __future__ import annotations

import httpx2
import pytest
from sm_ai.connections import pinned
from sm_ai.core.url_safety import UnsafeURLError

from tests.support.ai_test_stubs import fake_dns


@pytest.fixture
def wire(monkeypatch):
    """Replace the real connection layer; returns the requests it was handed."""
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if request.url.path == "/redirect":
            return httpx2.Response(302, headers={"location": "http://internal.example/meta"})
        return httpx2.Response(200, json={"ok": True})

    monkeypatch.setattr(pinned, "_inner_transport", lambda: httpx2.MockTransport(handler))
    return seen


async def test_dials_the_validated_address_with_the_name_kept(monkeypatch, wire):
    fake_dns(monkeypatch, {"api.example": ["93.184.216.34"]})
    async with pinned.pinned_client() as client:
        response = await client.get("https://api.example/v1/models")
    assert response.status_code == 200
    [sent] = wire
    assert sent.url.host == "93.184.216.34"
    assert sent.headers["host"] == "api.example"
    assert sent.extensions["sni_hostname"] == "api.example"


async def test_a_private_answer_is_refused_before_any_connection(monkeypatch, wire):
    fake_dns(monkeypatch, {"api.example": ["169.254.169.254"]})
    async with pinned.pinned_client() as client:
        with pytest.raises(UnsafeURLError, match="non_public_address"):
            await client.get("https://api.example/v1/models")
    assert wire == []


async def test_every_request_is_resolved_again(monkeypatch, wire):
    # DNS rebinding: a public answer first, a private one next time.
    answers = {"api.example": ["93.184.216.34"]}
    asked = fake_dns(monkeypatch, answers)
    async with pinned.pinned_client() as client:
        await client.get("https://api.example/a")
        answers["api.example"] = ["127.0.0.1"]
        with pytest.raises(UnsafeURLError):
            await client.get("https://api.example/b")
    assert asked == ["api.example", "api.example"]
    assert len(wire) == 1


async def test_a_redirect_hop_is_validated_too(monkeypatch, wire):
    fake_dns(monkeypatch, {"api.example": ["93.184.216.34"], "internal.example": ["10.0.0.9"]})
    async with pinned.pinned_client() as client:
        with pytest.raises(UnsafeURLError):
            await client.get("https://api.example/redirect", follow_redirects=True)
    assert [r.url.path for r in wire] == ["/redirect"]


async def test_a_slow_resolver_fails_closed(monkeypatch, wire):
    import time

    from sm_ai.core import url_safety

    monkeypatch.setattr(pinned, "DNS_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(url_safety.socket, "getaddrinfo", lambda *a, **k: time.sleep(0.5))
    async with pinned.pinned_client() as client:
        with pytest.raises(UnsafeURLError, match="unresolvable_host"):
            await client.get("https://api.example/v1")


def test_the_client_ignores_proxy_variables(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")
    client = pinned.pinned_client()
    assert client.trust_env is False
    assert isinstance(client._transport, pinned.PinnedTransport)
