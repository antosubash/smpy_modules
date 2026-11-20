"""One fetch of a subscription feed: conditional, capped, every hop checked.

The request is built here and handed **directly** to ``PinnedTransport``, never to an
``httpx.AsyncClient``: the client logs ``HTTP Request: GET <full URL>`` at INFO, which would write
the address's token into the log, and it brings a cookie jar, auth flows, proxy mounts and
environment reading this fetch must not have. What goes out is exactly ``Host`` (from the URL), a
fixed generic ``User-Agent``, ``Accept``, ``Accept-Encoding: identity`` and, on the first hop
only, ``If-None-Match`` / ``If-Modified-Since``. No cookie, no ``Authorization``, no ``Referer``,
ever: the address is the only credential and it is in the URL.

Redirects are followed by hand, at most ``SUBSCRIPTION_MAX_REDIRECTS``; each target is
normalised (``webcal:`` included), refused on an ``https`` to ``http`` downgrade, and sent through
the transport again, which resolves, checks and pins it from scratch. One absolute deadline covers
every hop's lookup, connect, handshake, headers and body.

The body is the raw bytes on the wire: ``Accept-Encoding: identity`` is sent and an encoded answer
is refused, so no decoder can inflate past the cap. A declared length over the cap is refused
before reading, and the stream is cut at the cap whatever it declared. The content type is not
trusted: a few are accepted by name to stop a login page early, and PR 5's ``sniff`` on the first
bytes is the real check.

Every failure is a :class:`FetchFailure` carrying a code, with the library's exception dropped
(its message can quote the address).
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from importlib import metadata
from typing import Final, Literal

import httpx

from sm_events.core import constants
from sm_events.feeds.importing.scan import sniff
from sm_events.feeds.subscriptions import policy as url_policy
from sm_events.feeds.subscriptions.client import PinnedTransport
from sm_events.feeds.subscriptions.errors import FetchFailure
from sm_events.feeds.subscriptions.fetch_signals import failure_of, max_age, retry_after
from sm_events.feeds.subscriptions.url_safety import UnsafeURLError

__all__ = ["USER_AGENT", "FetchFailure", "FetchResult", "fetch_feed"]

logger = logging.getLogger(__name__)

_REDIRECTS: Final = frozenset({301, 302, 303, 307, 308})
_IDENTITY: Final = frozenset({"", "identity"})
_TIMEOUTS: Final = {
    "connect": constants.FETCH_CONNECT_SECONDS,
    "read": constants.FETCH_READ_SECONDS,
    "write": constants.FETCH_WRITE_SECONDS,
    "pool": constants.FETCH_POOL_SECONDS,
}


def _user_agent() -> str:
    try:
        version = metadata.version(constants.DISTRIBUTION)
    except metadata.PackageNotFoundError:  # a source checkout without metadata
        version = "dev"
    return f"{constants.FETCH_USER_AGENT_PREFIX}/{version}"


USER_AGENT: Final = _user_agent()
"""Names neither the site, nor a tenant, nor a person: the same on every install."""


@dataclass(frozen=True)
class FetchResult:
    status: Literal["ok", "not_modified"]
    body: bytes
    """The raw feed; ``b""`` for ``not_modified``."""
    etag: str | None
    last_modified: str | None
    http_status: int
    max_age: int | None = None
    """``Cache-Control: max-age`` in seconds when the server gave a positive one."""


def _printable(value: str | None, limit: int) -> str | None:
    """``value`` when it is short printable ASCII (safe to store and to send back), else None."""
    if not value or len(value) > limit or not all(" " <= c <= "~" for c in value):
        return None
    return value


def _request(
    url: str, etag: str | None, last_modified: str | None, *, first: bool
) -> httpx.Request:
    headers = {
        "user-agent": USER_AGENT,
        "accept": constants.FETCH_ACCEPT,
        "accept-encoding": "identity",
    }
    if first:
        if tag := _printable(etag, constants.SUBSCRIPTION_ETAG_MAX):
            headers["if-none-match"] = tag
        if stamp := _printable(last_modified, constants.SUBSCRIPTION_LAST_MODIFIED_MAX):
            headers["if-modified-since"] = stamp
    return httpx.Request("GET", url, headers=headers, extensions={"timeout": dict(_TIMEOUTS)})


async def _send(
    transport: httpx.AsyncBaseTransport, request: httpx.Request, deadline: float
) -> httpx.Response:
    """Resolution, checking, connecting across the addresses and the response headers."""
    try:
        async with asyncio.timeout_at(deadline):
            return await transport.handle_async_request(request)
    except (TimeoutError, UnsafeURLError, FetchFailure, httpx.TransportError) as error:
        raise failure_of(error) from None
    except (httpx.InvalidURL, ValueError, UnicodeError):
        raise FetchFailure("url_invalid") from None
    except Exception:  # whatever the layer below raised can quote the address: only a code leaves
        raise FetchFailure("connect_failed") from None


async def _read(response: httpx.Response, max_bytes: int, deadline: float) -> bytes:
    """The raw body, each read inside the deadline, cut at ``max_bytes``."""
    chunks = response.aiter_raw()
    body = bytearray()
    try:
        while True:
            try:
                async with asyncio.timeout_at(deadline):
                    chunk = await anext(chunks)
            except StopAsyncIteration:
                return bytes(body)
            except (TimeoutError, httpx.TransportError) as error:
                raise failure_of(error) from None
            except Exception:
                raise FetchFailure("connect_failed") from None
            body += chunk
            if len(body) > max_bytes:
                raise FetchFailure("too_large")
    finally:
        await chunks.aclose()


def _next_url(current: str, response: httpx.Response, hop: int, policy: url_policy.Policy) -> str:
    """The redirect's target: joined, normalised (``webcal:`` included) and put through the
    address policy's syntactic half (so ``http:`` and a literal private address are refused as
    such), then refused if it downgrades ``https``. The transport resolves and checks it again."""
    location = response.headers.get("location")
    if not location:
        raise FetchFailure("http_status", http_status=response.status_code)
    if hop == constants.SUBSCRIPTION_MAX_REDIRECTS:
        raise FetchFailure("too_many_redirects")
    try:
        target = url_policy.normalise(str(httpx.URL(current).join(location)))
        url_policy.check(target, policy)
    except UnsafeURLError as error:
        raise FetchFailure(url_policy.user_code(error)) from None
    except (httpx.InvalidURL, ValueError, UnicodeError):
        raise FetchFailure("url_invalid") from None
    if httpx.URL(current).scheme == "https" and httpx.URL(target).scheme != "https":
        raise FetchFailure("insecure_redirect")
    return target


def _media_type(response: httpx.Response) -> str:
    return response.headers.get("content-type", "").split(";", 1)[0].strip().lower()


async def _final(
    response: httpx.Response, *, hop: int, conditional: bool, max_bytes: int, deadline: float
) -> FetchResult:
    status = response.status_code
    if status == 304 and hop == 0 and conditional:
        return FetchResult("not_modified", b"", None, None, status, max_age(response))
    if status == 410:
        raise FetchFailure("gone", http_status=status)
    if not 200 <= status < 300:
        raise FetchFailure("http_status", http_status=status, retry_after=retry_after(response))
    if response.headers.get("content-encoding", "").strip().lower() not in _IDENTITY:
        raise FetchFailure("unsupported_encoding")
    if (kind := _media_type(response)) and kind not in constants.FETCH_MEDIA_TYPES:
        raise FetchFailure("unexpected_content_type")
    try:
        declared = int(response.headers["content-length"])
    except (KeyError, ValueError):
        declared = None
    if declared is not None and declared > max_bytes:
        raise FetchFailure("too_large")
    body = await _read(response, max_bytes, deadline)
    if not sniff(body):
        raise FetchFailure("ics_invalid")
    return FetchResult(
        "ok",
        body,
        _printable(response.headers.get("etag"), constants.SUBSCRIPTION_ETAG_MAX),
        _printable(response.headers.get("last-modified"), constants.SUBSCRIPTION_LAST_MODIFIED_MAX),
        status,
        max_age(response),
    )


async def _fetch_feed(
    url: str,
    *,
    policy: url_policy.Policy,
    etag: str | None,
    last_modified: str | None,
    max_bytes: int,
    timeout: float = constants.SUBSCRIPTION_FETCH_SECONDS,
    transport_factory: Callable[[url_policy.Policy], httpx.AsyncBaseTransport] | None = None,
    gate: Callable[[str], Awaitable[None]] | None = None,
) -> FetchResult:
    """GET ``url`` (and at most ``SUBSCRIPTION_MAX_REDIRECTS`` redirects) under ``policy``.

    ``etag`` / ``last_modified`` are the validators of the last 200; they are sent on the first
    hop only. Raises :class:`FetchFailure` for everything that is not a 200 body or a 304.
    """
    deadline = asyncio.get_running_loop().time() + timeout
    factory = transport_factory or functools.partial(PinnedTransport, gate=gate)
    try:
        current = url_policy.normalise(url)
    except UnsafeURLError as error:
        raise FetchFailure(url_policy.user_code(error)) from None
    for hop in range(constants.SUBSCRIPTION_MAX_REDIRECTS + 1):
        transport = factory(policy)
        try:
            request = _request(current, etag, last_modified, first=hop == 0)
            response = await _send(transport, request, deadline)
            try:
                if response.status_code in _REDIRECTS:
                    current = _next_url(current, response, hop, policy)
                    continue
                return await _final(
                    response,
                    hop=hop,
                    conditional=bool(etag or last_modified),
                    max_bytes=max_bytes,
                    deadline=deadline,
                )
            finally:
                await response.aclose()
        finally:
            await transport.aclose()
    raise AssertionError("unreachable")  # pragma: no cover - the last hop returns or raises


async def fetch_feed(
    url: str,
    *,
    policy: url_policy.Policy,
    etag: str | None,
    last_modified: str | None,
    max_bytes: int,
    timeout: float = constants.SUBSCRIPTION_FETCH_SECONDS,
    transport_factory: Callable[[url_policy.Policy], httpx.AsyncBaseTransport] | None = None,
    gate: Callable[[str], Awaitable[None]] | None = None,
) -> FetchResult:
    """GET ``url`` (and at most ``SUBSCRIPTION_MAX_REDIRECTS`` redirects) under ``policy``.

    ``etag`` / ``last_modified`` are the validators of the last 200; they are sent on the first
    hop only. Raises :class:`FetchFailure` for everything that is not a 200 body or a 304, and
    **only** that: what leaves carries a code and no cause or context, because the exception that
    caused it can quote the address.
    """
    try:
        return await _fetch_feed(
            url,
            policy=policy,
            etag=etag,
            last_modified=last_modified,
            max_bytes=max_bytes,
            timeout=timeout,
            transport_factory=transport_factory,
            gate=gate,
        )
    except FetchFailure as failure:
        failure.__cause__ = failure.__context__ = None
        failure.__suppress_context__ = True
        raise
