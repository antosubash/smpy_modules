"""The pinned transport: validate every request's host, then connect only to its checked IPs.

**How the pin works.** :class:`PinnedTransport` resolves and checks the host of *every* request it
sends (the first and every redirect hop: :func:`sm_events.feeds.subscriptions.dns.resolve_bounded`)
and rewrites only the URL's *host* to a checked IP before handing the request to the real
transport. There is no second lookup anywhere below it, so the address that passed the guard is
the address dialled (the DNS-rebinding defence). The request keeps the ``Host`` header httpx built
from the original URL and gets the ``sni_hostname`` extension, which httpcore uses as the TLS
``server_hostname``: SNI is the name and, with the default ``verify=True`` context, the
certificate is verified against the name, never the IP (``test_client_tls`` proves both over a real
socket).

The URL rewrite uses public httpx extensions only; the one weakness of that route, a connection
pool keyed by IP, is closed here: each original origin (scheme, name, port) gets its own
connection layer, and keep-alive is off, so no connection verified for one name can serve another.
Only connect failures (nothing sent yet) move on to the next checked address, at most
``MAX_ADDRESSES_PER_HOP`` of them. ``trust_env=False``: proxy variables would otherwise mount a
proxy ahead of the pinned transport, and the proxy would resolve the name itself.

The transport is driven directly by :func:`sm_events.feeds.subscriptions.fetch.fetch_feed` (never
through an ``httpx.AsyncClient``, which logs every request line with its full URL).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import httpx

from sm_events.core import constants
from sm_events.feeds.subscriptions import dns
from sm_events.feeds.subscriptions.errors import FetchFailure
from sm_events.feeds.subscriptions.netsafe import harden
from sm_events.feeds.subscriptions.policy import Policy

__all__ = ["PinnedTransport", "inner_transport"]

logger = logging.getLogger(__name__)


def inner_transport() -> httpx.AsyncBaseTransport:
    """The real connection layer. Tests replace it; production never does."""
    return httpx.AsyncHTTPTransport(
        verify=True, trust_env=False, limits=httpx.Limits(max_keepalive_connections=0)
    )


class PinnedTransport(httpx.AsyncBaseTransport):
    """Validate every request's host and connect only to its checked IPs."""

    def __init__(
        self,
        policy: Policy,
        *,
        inner: Callable[[], httpx.AsyncBaseTransport] | None = None,
        gate: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._policy = policy
        self._gate = gate  # awaited with the server's IP before any connection; may raise
        self._factory = inner or inner_transport
        self._inners: dict[tuple[str, str, int | None], httpx.AsyncBaseTransport] = {}

    def _inner_for(self, url: httpx.URL) -> httpx.AsyncBaseTransport:
        origin = (url.scheme, url.host, url.port)
        if origin not in self._inners:
            self._inners[origin] = harden(self._factory())
        return self._inners[origin]

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host, ips = await dns.resolve_bounded(request.url, self._policy)
        inner = self._inner_for(request.url)
        extensions = dict(request.extensions)
        if request.url.scheme == "https":
            extensions["sni_hostname"] = host
        last_error: httpx.TransportError | None = None
        held_back: FetchFailure | None = None
        for ip in ips[: constants.MAX_ADDRESSES_PER_HOP]:
            if self._gate is not None:
                # The floor is on the server, so it is checked on each address about to be
                # connected to: a connect that fails still used that address's attempt, and an
                # address over its floor is not connected to (the next one gets its own check).
                try:
                    await self._gate(ip)
                except FetchFailure as later:
                    if later.code != "try_later":
                        raise
                    held_back = later
                    continue
            pinned = httpx.Request(
                method=request.method,
                url=request.url.copy_with(host=ip),
                headers=request.headers,  # carries Host: <name>, set from the original URL
                stream=request.stream,
                extensions=extensions,
            )
            try:
                return await inner.handle_async_request(pinned)
            except (httpx.ConnectError, httpx.ConnectTimeout) as error:
                logger.info("Pinned address failed to connect, trying the next")
                last_error = error
        if held_back is not None:  # an address was not contacted: try again after its floor
            raise held_back  # (not the feed's failure, even if another address refused)
        assert last_error is not None  # resolution never returns no addresses
        raise last_error

    async def aclose(self) -> None:
        inners, self._inners = list(self._inners.values()), {}
        for inner in inners:
            await inner.aclose()
