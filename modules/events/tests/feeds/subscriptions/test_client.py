"""The pinned transport: one resolution per request, and the connection goes to the address
that was checked, with the Host and SNI of the original name."""

from __future__ import annotations

import asyncio
import socket
import threading
import time

import httpx
import pytest
from sm_events.core import constants
from sm_events.feeds.subscriptions import client, dns, netsafe, policy
from sm_events.feeds.subscriptions.errors import FetchFailure
from sm_events.feeds.subscriptions.url_safety import UnsafeURLError

from tests.support.net import (  # noqa: F401 - fixtures
    OTHER_PUBLIC_IP,
    PUBLIC_IP,
    PUBLIC_IPV6,
    fake_dns,
    info,
    inner,
    resolver,
)

OFF = policy.Policy(allow_private=False)


def _request(url="https://cal.example/feed.ics", **extensions) -> httpx.Request:
    return httpx.Request("GET", url, extensions=extensions)


def _transport(handler, seen: list | None = None, pol=OFF) -> client.PinnedTransport:
    def wrapped(request):
        if seen is not None:
            seen.append(request)
        return handler(request)

    return client.PinnedTransport(pol, inner=lambda: httpx.MockTransport(wrapped))


async def test_connection_pinned_with_host_and_sni(resolver):  # noqa: F811
    resolver["cal.example"] = [PUBLIC_IP]
    seen: list[httpx.Request] = []
    transport = _transport(lambda r: httpx.Response(200), seen)
    response = await transport.handle_async_request(_request())
    assert response.status_code == 200
    (got,) = seen
    assert got.url.host == PUBLIC_IP
    assert got.headers["host"] == "cal.example"
    assert got.extensions["sni_hostname"] == "cal.example"
    assert got.url.path == "/feed.ics"


async def test_a_non_default_port_survives_the_rewrite(resolver):  # noqa: F811
    resolver["cal.example"] = [PUBLIC_IP]
    seen: list[httpx.Request] = []
    pol = policy.Policy(allow_private=True, may_use_private=True)
    await _transport(lambda r: httpx.Response(200), seen, pol).handle_async_request(
        _request("https://cal.example:8443/x")
    )
    assert seen[0].url.port == 8443
    assert seen[0].headers["host"] == "cal.example:8443"


async def test_connection_pinned_to_checked_address(monkeypatch):
    """DNS rebinding: public on the first answer, loopback on every later one. The one
    resolution that was checked is the one dialled, and the next request is refused."""
    calls = {"n": 0}

    def rebinding(host, port, *args, **kwargs):
        calls["n"] += 1
        return [info(host, PUBLIC_IP if calls["n"] == 1 else "127.0.0.1", port)]

    fake_dns(monkeypatch, rebinding)
    seen: list[httpx.Request] = []
    transport = _transport(lambda r: httpx.Response(200), seen)
    await transport.handle_async_request(_request())
    assert [r.url.host for r in seen] == [PUBLIC_IP]
    assert calls["n"] == 1  # no second lookup anywhere inside the client
    with pytest.raises(UnsafeURLError):
        await transport.handle_async_request(_request())
    assert [r.url.host for r in seen] == [PUBLIC_IP]


async def test_a_public_and_a_private_record_is_refused_outright(resolver):  # noqa: F811
    resolver["cal.example"] = [PUBLIC_IP, "10.0.0.1"]
    seen: list = []
    with pytest.raises(UnsafeURLError):
        await _transport(lambda r: httpx.Response(200), seen).handle_async_request(_request())
    assert seen == []


async def test_ipv6_pinned(resolver):  # noqa: F811
    resolver["cal.example"] = [PUBLIC_IPV6]
    seen: list[httpx.Request] = []
    await _transport(lambda r: httpx.Response(200), seen).handle_async_request(_request())
    assert seen[0].url.host == PUBLIC_IPV6
    assert seen[0].headers["host"] == "cal.example"


async def test_dead_first_address_falls_back(resolver):  # noqa: F811
    resolver["cal.example"] = [PUBLIC_IP, OTHER_PUBLIC_IP]
    seen: list[httpx.Request] = []

    def handler(request):
        if request.url.host == PUBLIC_IP:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200)

    response = await _transport(handler, seen).handle_async_request(_request())
    assert response.status_code == 200
    assert [r.url.host for r in seen] == [PUBLIC_IP, OTHER_PUBLIC_IP]


async def test_non_connect_errors_do_not_retry(resolver):  # noqa: F811
    resolver["cal.example"] = [PUBLIC_IP, OTHER_PUBLIC_IP]
    seen: list[httpx.Request] = []

    def handler(request):
        raise httpx.ReadError("reset", request=request)  # something was already sent

    with pytest.raises(httpx.ReadError):
        await _transport(handler, seen).handle_async_request(_request())
    assert len(seen) == 1


async def test_at_most_four_addresses(resolver):  # noqa: F811
    resolver["many.example"] = [f"93.184.216.{n}" for n in range(30, 37)]
    seen: list[httpx.Request] = []

    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(httpx.ConnectError):
        await _transport(handler, seen).handle_async_request(_request("https://many.example/x"))
    assert len(seen) == constants.MAX_ADDRESSES_PER_HOP == 4


async def test_private_refused_before_connect(resolver):  # noqa: F811
    resolver["internal.example"] = ["10.0.0.5"]
    seen: list = []
    with pytest.raises(UnsafeURLError) as caught:
        await _transport(lambda r: httpx.Response(200), seen).handle_async_request(
            _request("https://internal.example/x")
        )
    assert caught.value.code == "non_public_address"
    assert seen == []


async def test_the_scheme_policy_applies_inside_the_transport_too(resolver):  # noqa: F811
    resolver["cal.example"] = [PUBLIC_IP]
    seen: list = []
    with pytest.raises(UnsafeURLError) as caught:
        await _transport(lambda r: httpx.Response(200), seen).handle_async_request(
            _request("http://cal.example/x")
        )
    assert caught.value.code == "invalid_scheme"
    assert seen == []


async def test_dns_timeout_fails_closed(monkeypatch):
    release = threading.Event()

    def hang(*_a, **_k):
        release.wait(10)
        raise OSError("released")

    fake_dns(monkeypatch, hang)
    monkeypatch.setattr(dns, "DNS_TIMEOUT_SECONDS", 0.2)
    started = time.monotonic()
    try:
        with pytest.raises(FetchFailure) as caught:
            await _transport(lambda r: httpx.Response(200)).handle_async_request(_request())
    finally:
        release.set()
    assert caught.value.code == "url_unreachable"
    assert time.monotonic() - started < constants.DNS_TIMEOUT_SECONDS + 1


async def test_proxy_env_ignored(resolver, monkeypatch):  # noqa: F811
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "HTTP_PROXY"):
        monkeypatch.setenv(name, "http://proxy.invalid:3128")
    resolver["cal.example"] = [PUBLIC_IP]
    seen: list[httpx.Request] = []
    await _transport(lambda r: httpx.Response(200), seen).handle_async_request(_request())
    assert seen[0].url.host == PUBLIC_IP
    real = client.inner_transport()
    assert real._pool.__class__.__name__ == "AsyncConnectionPool"  # no proxy pool mounted
    await real.aclose()


async def test_one_transport_never_shares_a_pool_between_names(resolver):  # noqa: F811
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

    transport = client.PinnedTransport(OFF, inner=factory)
    for url in ("https://a.example/1", "https://b.example/1", "https://a.example/2"):
        assert (await transport.handle_async_request(httpx.Request("GET", url))).status_code == 200
    assert made == [["a.example", "a.example"], ["b.example"]]
    await transport.aclose()


def test_the_real_transport_keeps_no_connections_alive_and_is_hardened():
    real = client.inner_transport()
    assert real._pool._max_keepalive_connections == 0
    hardened = netsafe.harden(real)
    assert isinstance(real._pool._network_backend, netsafe.CancelSafeBackend)
    assert netsafe.harden(hardened) is hardened  # idempotent


async def test_cancelled_resolution_is_not_swallowed(monkeypatch):
    release = threading.Event()

    def hang(*_a, **_k):
        release.wait(10)
        raise OSError("released")

    fake_dns(monkeypatch, hang)
    task = asyncio.ensure_future(
        _transport(lambda r: httpx.Response(200)).handle_async_request(_request())
    )
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()


def test_socket_is_the_guards_not_the_global(resolver):  # noqa: F811
    """The fake lives on the guard's module attribute only: nothing else is faked."""
    assert socket.getaddrinfo is not None
    from sm_events.feeds.subscriptions import url_safety

    assert url_safety.socket is not socket
