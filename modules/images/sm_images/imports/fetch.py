"""Download primitives: an IP-pinned transport and :func:`safe_stream`.

Ported from the portal's ``download_security`` (``PinnedDNSTransport``,
``open_safe_stream``) and ``download_utils`` (the byte cap).

**How the pin works.** :class:`PinnedTransport` runs :func:`resolve_public` for
every request it sends - the first and every redirect hop - and rewrites only
the URL's *host* to a validated IP before handing it to the real transport. The
request keeps the ``Host`` header httpx built from the original URL, and gets
the ``sni_hostname`` extension, which httpcore uses as ``server_hostname`` for
the TLS handshake: SNI is the name and, with the default ``verify=True``
context (``check_hostname``), the certificate is verified against the name, not
the IP. (``tests/test_imports_fetch_tls.py`` proves both over a real socket.)

Why this and not a custom httpcore network backend that maps the name to the IP
inside ``connect_tcp``: httpx's ``AsyncHTTPTransport`` takes no network backend,
so that route means replacing its private ``_pool`` or re-implementing its
exception and stream mapping. The URL rewrite uses public extensions only. Its
one weakness - the connection pool is keyed by IP, so two names on one IP could
share a TLS connection made for the first name - is closed inside the
transport: each original origin (scheme, name, port) gets its own connection
layer, so even a reused ``PinnedTransport`` verifies every name.

Only connect failures (nothing sent yet) move on to the next validated address,
and at most ``MAX_ADDRESSES_PER_HOP`` are tried. Resolution runs on a small
dedicated thread pool under its own timeout, and one absolute deadline covers a
whole fetch.
Redirects are followed by hand (``follow_redirects=False``), at most five, each
hop re-checked. ``trust_env=False``: proxy env vars would otherwise mount proxy
transports ahead of the pinned one.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from importlib import metadata
from typing import Final

import httpx

from sm_images.imports.dns import resolve_bounded
from sm_images.imports.errors import FetchError, FetchTimeoutError, FetchTooLargeError
from sm_images.imports.netsafe import harden
from sm_images.imports.url_safety import DEFAULT_ALLOWED_PORTS, UnsafeURLError, check_url

__all__ = [
    "MAX_REDIRECTS",
    "FetchError",
    "FetchTimeoutError",
    "FetchTooLargeError",
    "USER_AGENT",
    "PinnedTransport",
    "safe_stream",
]

logger = logging.getLogger(__name__)

MAX_REDIRECTS: Final = 5
MAX_ADDRESSES_PER_HOP: Final = 4
_IDENTITY: Final = frozenset({"", "identity"})


def _user_agent() -> str:
    try:
        version = metadata.version("simple_module_images")
    except metadata.PackageNotFoundError:  # a source checkout without metadata
        version = "dev"
    return f"SimpleModule-Images/{version} (+{REPOSITORY_URL}) python-httpx/{httpx.__version__}"


REPOSITORY_URL: Final = "https://github.com/antosubash/simple_module_python_modules"
USER_AGENT: Final = _user_agent()
"""Sent on every hop: hosts such as Wikimedia refuse the library's default
(their policy asks for ``<client>/<version> (<contact>)``)."""


def _inner_transport() -> httpx.AsyncBaseTransport:
    """The real connection layer. Tests replace it; production never does."""
    return httpx.AsyncHTTPTransport(verify=True, trust_env=False)


class PinnedTransport(httpx.AsyncBaseTransport):
    """Validate every request's host and connect only to its validated IPs.

    The connection layer is partitioned by the request's *original* origin
    (scheme, name, port): its pool is keyed by the pinned IP, so a shared one
    would let a TLS connection verified for one name serve another name on the
    same IP. Each origin gets its own, so an instance is safe to reuse.
    """

    def __init__(
        self,
        *,
        allowed_ports: frozenset[int] = DEFAULT_ALLOWED_PORTS,
        inner: Callable[[], httpx.AsyncBaseTransport] | None = None,
    ) -> None:
        self._allowed_ports = allowed_ports
        self._factory = inner or _inner_transport
        self._inners: dict[tuple[str, str, int | None], httpx.AsyncBaseTransport] = {}

    def _inner_for(self, url: httpx.URL) -> httpx.AsyncBaseTransport:
        origin = (url.scheme, url.host, url.port)
        if origin not in self._inners:
            self._inners[origin] = harden(self._factory())
        return self._inners[origin]

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host, ips = await resolve_bounded(request.url, self._allowed_ports)
        inner = self._inner_for(request.url)
        extensions = dict(request.extensions)
        if request.url.scheme == "https":
            extensions["sni_hostname"] = host
        last_error: httpx.TransportError | None = None
        for ip in ips[:MAX_ADDRESSES_PER_HOP]:
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
                logger.info(
                    "Pinned address failed to connect, trying the next",
                    extra={"host": host, "ip": ip},
                )
                last_error = error
        assert last_error is not None  # resolve_public never returns no addresses
        raise last_error

    async def aclose(self) -> None:
        inners, self._inners = list(self._inners.values()), {}
        for inner in inners:
            await inner.aclose()


def _client(timeout: float, allowed_ports: frozenset[int]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=PinnedTransport(allowed_ports=allowed_ports),
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        headers={"accept-encoding": "identity", "user-agent": USER_AGENT},
    )


def _declared_length(response: httpx.Response) -> int | None:
    try:
        return int(response.headers["content-length"])
    except (KeyError, ValueError):
        return None


async def safe_stream(
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    max_redirects: int = MAX_REDIRECTS,
    allowed_ports: frozenset[int] = DEFAULT_ALLOWED_PORTS,
    on_redirect: Callable[[httpx.URL], Awaitable[None]] | None = None,
) -> AsyncIterator[bytes]:
    """GET ``url`` and yield its body as delivered, at most ``max_bytes`` of it.

    ``on_redirect(target)`` is awaited before each redirect hop is requested,
    inside the deadline - the caller's chance to take that host's download
    slot (``retrying``), so a redirect cannot bypass a per-domain cap.

    ``timeout`` is both httpx's per-operation timeout and one absolute deadline
    for the whole fetch: every hop's resolution, connects, headers and each body
    read run under ``asyncio.timeout_at`` and expiry is ``FetchTimeoutError``.
    The body is the raw bytes on the wire: ``Accept-Encoding: identity`` is
    sent and a content-encoded answer is refused, so no decoder can inflate
    past the cap.

    Raises:
        UnsafeURLError: the URL or a redirect target fails the guard, or more
            than ``max_redirects`` redirects. Permanent.
        httpx.HTTPStatusError: a non-2xx final answer; ``.response`` carries the
            status and headers for :func:`~sm_images.imports.rate_limit.backoff`.
        FetchTooLargeError, FetchTimeoutError, FetchError("unsupported_encoding").
        httpx.TransportError: the network failed (retryable).
    """
    deadline = asyncio.get_running_loop().time() + timeout
    check_url(url, allowed_ports=allowed_ports)
    current = httpx.URL(url.strip())
    for hop in range(max_redirects + 1):
        async with _client(timeout, allowed_ports) as client:
            request = client.build_request("GET", current)
            try:  # resolution, connecting across the addresses, headers
                async with asyncio.timeout_at(deadline):
                    response = await client.send(request, stream=True)
            except TimeoutError as error:
                raise FetchTimeoutError() from error
            try:
                if response.has_redirect_location:
                    if hop == max_redirects:  # before the hook: no slot for a hop never fetched
                        raise UnsafeURLError("too_many_redirects")
                    current = current.join(response.headers["location"])
                    check_url(current, allowed_ports=allowed_ports)  # the transport re-checks
                    logger.info("Following redirect", extra={"hop": hop + 1, "host": current.host})
                    if on_redirect is not None:
                        try:
                            async with asyncio.timeout_at(deadline):
                                await on_redirect(current)
                        except TimeoutError as error:
                            raise FetchTimeoutError() from error
                    continue
                _check_final(response, max_bytes)
                async for chunk in _capped_body(response, max_bytes, deadline):
                    yield chunk
                return
            finally:
                await response.aclose()
    raise AssertionError("unreachable")  # pragma: no cover - the last hop returns or raises


def _check_final(response: httpx.Response, max_bytes: int) -> None:
    response.raise_for_status()
    if response.headers.get("content-encoding", "").strip().lower() not in _IDENTITY:
        raise FetchError("unsupported_encoding")
    declared = _declared_length(response)
    if declared is not None and declared > max_bytes:
        raise FetchTooLargeError()


async def _capped_body(
    response: httpx.Response, max_bytes: int, deadline: float
) -> AsyncIterator[bytes]:
    """The raw body, each read inside the deadline (``yield`` stays outside it,
    so the consumer's own time is never cancelled by it)."""
    chunks = response.aiter_raw()
    received = 0
    try:
        while True:
            try:
                async with asyncio.timeout_at(deadline):
                    chunk = await anext(chunks)
            except StopAsyncIteration:
                return
            except TimeoutError as error:
                raise FetchTimeoutError() from error
            received += len(chunk)
            if received > max_bytes:
                raise FetchTooLargeError()
            yield chunk
    finally:
        await chunks.aclose()
