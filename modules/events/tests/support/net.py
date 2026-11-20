"""Fixtures for the subscription fetch tests: a fake resolver and a fake connection layer.

Nothing here touches the network. ``resolver`` replaces ``getaddrinfo`` inside events'
``url_safety`` (never ``socket.getaddrinfo`` itself: that would fake DNS for the database
driver too); ``inner`` replaces the connection layer the pinned transport dials through, so the
request a handler sees is exactly what would have gone on the wire.
"""

from __future__ import annotations

import socket

import httpx
import pytest
from sm_events.feeds.subscriptions import url_safety

ICS = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"
PUBLIC_IP = "93.184.216.34"
OTHER_PUBLIC_IP = "93.184.216.35"
PUBLIC_IPV6 = "2606:2800:220:1:248:1893:25c8:1946"


async def _chunks(data: bytes):
    yield data


def body(data: bytes, **headers: str) -> httpx.Response:
    """A 200 whose body arrives as a stream, as from a real server (a ``bytes`` body would
    count as already read)."""
    return httpx.Response(200, content=_chunks(data), headers=headers)


def info(host: str, ip: str, port: int):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return (family, socket.SOCK_STREAM, 6, "", (ip, port))


def ics(**headers: str) -> httpx.Response:
    """A streamed 200 holding a minimal calendar, ``text/calendar`` unless told otherwise."""
    return body(ICS, **{"content-type": "text/calendar", **headers})


async def fetch(url: str, *, intranet: bool = False, etag=None, last_modified=None, **kw):
    """``fetch_feed`` under the default policy (or the intranet switch), with test-sized
    limits; ``kw`` overrides ``max_bytes`` / ``timeout`` / ``transport_factory``."""
    from sm_events.feeds.subscriptions.fetch import fetch_feed
    from sm_events.feeds.subscriptions.policy import Policy

    kw.setdefault("max_bytes", 100_000)
    kw.setdefault("timeout", 5)
    return await fetch_feed(
        url,
        policy=Policy(allow_private=intranet, may_use_private=intranet),
        etag=etag,
        last_modified=last_modified,
        **kw,
    )


async def failure_code(url: str, **kw) -> str:
    """The code ``fetch`` fails with (the test fails if it succeeds)."""
    from sm_events.feeds.subscriptions.errors import FetchFailure

    try:
        await fetch(url, **kw)
    except FetchFailure as failure:
        return failure.code
    raise AssertionError("the fetch should have failed")


class FakeSocket:
    """``socket`` as ``url_safety`` sees it, with ``getaddrinfo`` replaced."""

    def __init__(self, getaddrinfo) -> None:
        self.getaddrinfo = getaddrinfo

    def __getattr__(self, name: str):
        return getattr(socket, name)


def fake_dns(monkeypatch, getaddrinfo) -> None:
    monkeypatch.setattr(url_safety, "socket", FakeSocket(getaddrinfo))


@pytest.fixture
def resolver(monkeypatch):
    """hostname -> list of IPs; an unknown host fails to resolve. ``resolver.calls`` counts
    lookups per host."""

    class Table(dict):
        calls: dict[str, int]

    table = Table()
    table.calls = {}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        table.calls[host] = table.calls.get(host, 0) + 1
        if host not in table:
            raise socket.gaierror("unknown host")
        return [info(host, ip, port) for ip in table[host]]

    fake_dns(monkeypatch, fake_getaddrinfo)
    return table


@pytest.fixture
def inner(monkeypatch):
    """``inner(handler)`` installs ``handler`` as the connection layer and returns the list of
    requests it receives."""
    from sm_events.feeds.subscriptions import client

    seen: list[httpx.Request] = []
    state: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return state["handler"](request)

    monkeypatch.setattr(client, "inner_transport", lambda: httpx.MockTransport(handler))

    def install(fn):
        state["handler"] = fn
        return seen

    return install
