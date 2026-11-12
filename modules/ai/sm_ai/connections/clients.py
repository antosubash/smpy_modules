"""The HTTP clients a slot's SDK client is built with, shared per event loop.

``resolve`` builds a model per call and pydantic-ai never closes a client it
did not create, so a new ``httpx2.AsyncClient`` per call (each with its own SSL
context) would pile up. Instead one client per (kind, base-URL origin) is kept
for each running event loop and handed to every model built on that loop:

* ``pinned`` - :func:`~sm_ai.connections.pinned.pinned_client`, for a base URL
  that must resolve to public addresses;
* ``private`` - with ``allow_private_base_url`` on: a plain client that does
  **not follow redirects** (the SDKs' own default clients do, and a followed
  hop would carry the key's header to another host) and keeps
  ``trust_env=True``, so an egress proxy still works.

Per loop, not per process: a connection pool and its locks belong to the loop
that used them, and a Celery task runs each call on a loop of its own. The
cache holds loops weakly, so a finished loop's clients go with it, and keeps at
most :data:`MAX_PER_LOOP` origins per loop (the oldest is dropped, not closed:
a model may still be using it, and neither kind keeps idle connections). Built with
no running loop (plain sync code), a client is not cached; discovery asks for
an unshared one and closes it itself.
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import Callable
from typing import Final

import httpx2

from sm_ai.connections.pinned import TIMEOUT, pinned_client

__all__ = ["MAX_PER_LOOP", "client_for", "private_client"]

MAX_PER_LOOP: Final = 8
Key = tuple[str, str, str, int | None]
_CACHE: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[Key, httpx2.AsyncClient]] = (
    weakref.WeakKeyDictionary()
)


def _private_transport() -> httpx2.AsyncBaseTransport | None:
    """``None`` (httpx's own, with env proxies). Tests replace it."""
    return None


def private_client() -> httpx2.AsyncClient:
    """A client for a private base URL: no redirects, environment proxies kept,
    and no idle connections - an idle one would keep its loop alive, and with it
    this cache's entry for a finished Celery loop."""
    return httpx2.AsyncClient(
        transport=_private_transport(),
        timeout=TIMEOUT,
        follow_redirects=False,
        limits=httpx2.Limits(max_keepalive_connections=0),
    )


_FACTORIES: Final[dict[str, Callable[[], httpx2.AsyncClient]]] = {
    "pinned": lambda: pinned_client(),
    "private": lambda: private_client(),
}


def client_for(kind: str, base_url: str, *, shared: bool = True) -> httpx2.AsyncClient:
    """The ``kind`` client for ``base_url``'s origin (``pinned`` or ``private``)."""
    factory = _FACTORIES[kind]
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if not shared or loop is None:
        return factory()
    url = httpx2.URL(base_url)
    key: Key = (kind, url.scheme, url.host, url.port)
    clients = _CACHE.setdefault(loop, {})
    client = clients.get(key)
    if client is not None and not client.is_closed:
        return client
    clients.pop(key, None)  # a closed entry never counts against the bound
    while len(clients) >= MAX_PER_LOOP:
        # Dropped, not closed: a model built earlier may be mid-request on it,
        # and neither kind holds idle connections, so nothing is left open.
        clients.pop(next(iter(clients)))
    client = clients[key] = factory()
    return client


def cached(loop: asyncio.AbstractEventLoop) -> int:
    """How many clients ``loop`` holds (tests)."""
    return len(_CACHE.get(loop, {}))
