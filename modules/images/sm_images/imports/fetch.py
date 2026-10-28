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
share a TLS connection made for the first name - is closed by giving every hop
its own client (and so its own pool).

Only connect failures (nothing sent yet) move on to the next validated address.
Redirects are followed by hand (``follow_redirects=False``), at most five, each
hop re-checked. ``trust_env=False``: proxy env vars would otherwise mount proxy
transports ahead of the pinned one.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from typing import Final

import httpx

from sm_images.imports.url_safety import (
    DEFAULT_ALLOWED_PORTS,
    UnsafeURLError,
    check_url,
    resolve_public,
)

__all__ = [
    "MAX_REDIRECTS",
    "FetchError",
    "FetchTimeoutError",
    "FetchTooLargeError",
    "PinnedTransport",
    "safe_stream",
]

logger = logging.getLogger(__name__)

MAX_REDIRECTS: Final = 5
_IDENTITY: Final = frozenset({"", "identity"})


class FetchError(Exception):
    """A fetch that failed for a reason worth recording. ``code`` is a constant."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class FetchTooLargeError(FetchError):
    """The body is (declared or actually) larger than ``max_bytes``. Permanent."""

    def __init__(self) -> None:
        super().__init__("too_large")


class FetchTimeoutError(FetchError):
    """The whole fetch overran its wall-clock budget (a trickling body). Retryable."""

    def __init__(self) -> None:
        super().__init__("timeout")


def _inner_transport() -> httpx.AsyncBaseTransport:
    """The real connection layer. Tests replace it; production never does."""
    return httpx.AsyncHTTPTransport(verify=True, trust_env=False)


def _now() -> float:
    return time.monotonic()


class PinnedTransport(httpx.AsyncBaseTransport):
    """Validate every request's host and connect only to its validated IPs."""

    def __init__(
        self,
        *,
        allowed_ports: frozenset[int] = DEFAULT_ALLOWED_PORTS,
        inner: Callable[[], httpx.AsyncBaseTransport] | None = None,
    ) -> None:
        self._allowed_ports = allowed_ports
        self._inner = (inner or _inner_transport)()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host, ips = await asyncio.to_thread(
            resolve_public, request.url, allowed_ports=self._allowed_ports
        )
        extensions = dict(request.extensions)
        if request.url.scheme == "https":
            extensions["sni_hostname"] = host
        last_error: httpx.TransportError | None = None
        for ip in ips:
            pinned = httpx.Request(
                method=request.method,
                url=request.url.copy_with(host=ip),
                headers=request.headers,  # carries Host: <name>, set from the original URL
                stream=request.stream,
                extensions=extensions,
            )
            try:
                return await self._inner.handle_async_request(pinned)
            except (httpx.ConnectError, httpx.ConnectTimeout) as error:
                logger.info(
                    "Pinned address failed to connect, trying the next",
                    extra={"host": host, "ip": ip},
                )
                last_error = error
        assert last_error is not None  # resolve_public never returns no addresses
        raise last_error

    async def aclose(self) -> None:
        await self._inner.aclose()


def _client(timeout: float, allowed_ports: frozenset[int]) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=PinnedTransport(allowed_ports=allowed_ports),
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        headers={"accept-encoding": "identity"},
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
) -> AsyncIterator[bytes]:
    """GET ``url`` and yield its body as delivered, at most ``max_bytes`` of it.

    ``timeout`` is both httpx's per-operation timeout and the wall-clock budget
    for the whole fetch, redirects included. The body is the raw bytes on the
    wire: ``Accept-Encoding: identity`` is sent and a content-encoded answer is
    refused, so no decoder can inflate past the cap.

    Raises:
        UnsafeURLError: the URL or a redirect target fails the guard, or more
            than ``max_redirects`` redirects. Permanent.
        httpx.HTTPStatusError: a non-2xx final answer; ``.response`` carries the
            status and headers for :func:`~sm_images.imports.rate_limit.backoff`.
        FetchTooLargeError, FetchTimeoutError, FetchError("unsupported_encoding").
        httpx.TransportError: the network failed (retryable).
    """
    deadline = _now() + timeout
    check_url(url, allowed_ports=allowed_ports)
    current = httpx.URL(url.strip())
    for hop in range(max_redirects + 1):
        if _now() > deadline:
            raise FetchTimeoutError()
        async with (
            _client(timeout, allowed_ports) as client,
            client.stream("GET", current) as response,
        ):
            if response.has_redirect_location:
                current = current.join(response.headers["location"])
                check_url(
                    current, allowed_ports=allowed_ports
                )  # fail fast; the transport re-checks
                logger.info("Following redirect", extra={"hop": hop + 1, "host": current.host})
                continue
            response.raise_for_status()
            if response.headers.get("content-encoding", "").strip().lower() not in _IDENTITY:
                raise FetchError("unsupported_encoding")
            declared = _declared_length(response)
            if declared is not None and declared > max_bytes:
                raise FetchTooLargeError()
            received = 0
            async for chunk in response.aiter_raw():
                received += len(chunk)
                if received > max_bytes:
                    raise FetchTooLargeError()
                if _now() > deadline:
                    raise FetchTimeoutError()
                yield chunk
            return
    raise UnsafeURLError("too_many_redirects")
