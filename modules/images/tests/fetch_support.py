"""Fixtures for the safe-fetch tests: a fake resolver and a fake connection layer.

Nothing here touches the network. ``resolver`` replaces ``getaddrinfo`` inside
``url_safety``; ``inner`` replaces the transport ``fetch`` dials through, so the
request a handler sees is exactly what would have gone on the wire.
"""

from __future__ import annotations

import socket

import httpx
import pytest
from sm_images.imports import fetch, url_safety

PUBLIC_IP = "93.184.216.34"
OTHER_PUBLIC_IP = "93.184.216.35"
PUBLIC_IPV6 = "2606:2800:220:1:248:1893:25c8:1946"


async def _chunks(data: bytes):
    yield data


def body(data: bytes) -> httpx.Response:
    """A 200 whose body arrives as a stream, as from a real server (a ``bytes``
    body would count as already read)."""
    return httpx.Response(200, content=_chunks(data))


@pytest.fixture
def resolver(monkeypatch):
    """hostname -> list of IPs; an unknown host fails to resolve."""
    table: dict[str, list[str]] = {}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host not in table:
            raise socket.gaierror("unknown host")
        return [
            (
                socket.AF_INET6 if ":" in ip else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (ip, port),
            )
            for ip in table[host]
        ]

    monkeypatch.setattr(url_safety.socket, "getaddrinfo", fake_getaddrinfo)
    return table


@pytest.fixture
def inner(monkeypatch):
    """``inner(handler)`` installs ``handler`` as the connection layer and returns
    the list of requests it receives."""
    seen: list[httpx.Request] = []
    state: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return state["handler"](request)

    monkeypatch.setattr(fetch, "_inner_transport", lambda: httpx.MockTransport(handler))

    def install(fn):
        state["handler"] = fn
        return seen

    return install
