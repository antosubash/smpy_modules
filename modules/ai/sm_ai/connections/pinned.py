"""An HTTP client that connects only to a validated public address (#347).

The provider SDKs (OpenAI, Anthropic, google-genai) all accept a caller's
``httpx2.AsyncClient``, so a slot with a base URL gets one whose transport is
:class:`PinnedTransport`: for every request it sends it resolves the host,
refuses it unless every address is public
(:func:`sm_ai.core.url_safety.resolve_public`), and rewrites only the URL's
*host* to one of those addresses before handing the request to a real
transport. The ``Host`` header still names the host, and on https the
``sni_hostname`` extension makes the TLS handshake send the name and verify
the certificate against it, not against the IP. The check and the connection
therefore use the same answer, and a DNS record that changes between them
(rebinding) cannot point the connection somewhere else.

Adapted from images' ``PinnedTransport`` (``sm_images.ingest.imports.fetch``),
on ``httpx2`` because that is what the SDKs speak, and with two
simplifications a provider call allows: resolution runs on the default thread
pool under :data:`DNS_TIMEOUT_SECONDS`, and the client keeps no idle
connections (``max_keepalive_connections=0``), so a connection closes when its
response does. One client is shared per event loop and origin
(:mod:`sm_ai.connections.clients`).

The client does not follow redirects (the SDKs' own default clients do, but a
followed hop would carry the key's header, ``x-api-key`` included, to another
host): a 3xx answer reaches the SDK as an error, so a base URL must be the final
one. Were redirects ever enabled, each hop passes through this transport and is
validated like the first request.

``trust_env=False``: a proxy taken from ``HTTPS_PROXY`` would resolve the name
itself, so a pinned client never uses one (see the module's operations docs).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

import httpx2

from sm_ai.core.url_safety import UnsafeURLError, resolve_public

__all__ = ["DNS_TIMEOUT_SECONDS", "TIMEOUT", "PinnedTransport", "pinned_client"]

logger = logging.getLogger(__name__)

DNS_TIMEOUT_SECONDS: float = 5.0
MAX_ADDRESSES: Final = 4
# pydantic-ai's own client defaults (``pydantic_ai._http``): a long read for a
# slow model, a short connect.
TIMEOUT: Final = httpx2.Timeout(timeout=600, connect=5)


async def resolve_bounded(url: str | httpx2.URL) -> tuple[str, tuple[str, ...]]:
    """``resolve_public`` off the event loop, failing closed on a slow resolver."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(resolve_public, url), DNS_TIMEOUT_SECONDS)
    except TimeoutError as error:
        raise UnsafeURLError("unresolvable_host") from error


def _inner_transport() -> httpx2.AsyncBaseTransport:
    """The real connection layer. Tests replace it; production never does."""
    return httpx2.AsyncHTTPTransport(
        verify=True,
        trust_env=False,
        limits=httpx2.Limits(max_keepalive_connections=0),
    )


class PinnedTransport(httpx2.AsyncBaseTransport):
    """Validate every request's host and connect only to its validated IPs.

    The connection layer is kept per *original* origin (scheme, name, port):
    its pool is keyed by the pinned IP, so a shared one could let a TLS
    connection verified for one name serve another name on the same IP.
    """

    def __init__(self) -> None:
        self._inners: dict[tuple[str, str, int | None], httpx2.AsyncBaseTransport] = {}

    def _inner_for(self, url: httpx2.URL) -> httpx2.AsyncBaseTransport:
        origin = (url.scheme, url.host, url.port)
        if origin not in self._inners:
            self._inners[origin] = _inner_transport()
        return self._inners[origin]

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        host, ips = await resolve_bounded(request.url)
        inner = self._inner_for(request.url)
        extensions = dict(request.extensions)
        if request.url.scheme == "https":
            extensions["sni_hostname"] = host
        last_error: httpx2.TransportError | None = None
        for ip in ips[:MAX_ADDRESSES]:
            pinned = httpx2.Request(
                method=request.method,
                url=request.url.copy_with(host=ip),
                headers=request.headers,  # carries Host: <name>, set from the original URL
                stream=request.stream,
                extensions=extensions,
            )
            try:
                return await inner.handle_async_request(pinned)
            except (httpx2.ConnectError, httpx2.ConnectTimeout) as error:
                logger.info(
                    "Pinned AI endpoint address failed to connect, trying the next",
                    extra={"host": host, "ip": ip},
                )
                last_error = error
        assert last_error is not None  # resolve_public never returns no addresses
        raise last_error

    async def aclose(self) -> None:
        inners, self._inners = list(self._inners.values()), {}
        for inner in inners:
            await inner.aclose()


def pinned_client() -> httpx2.AsyncClient:
    """A client for provider calls against a validated base URL (shared through
    :func:`sm_ai.connections.clients.client_for`)."""
    return httpx2.AsyncClient(transport=PinnedTransport(), timeout=TIMEOUT, trust_env=False)
