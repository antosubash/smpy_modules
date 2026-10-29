"""Fetching one image URL with the import retry policy (Task 16's rules).

* **Retryable** - a transport error, the deadline, 408/429/5xx: retried with
  :func:`~sm_images.imports.rate_limit.backoff`, at most
  :data:`INLINE_ATTEMPTS` times in one go. A wait longer than
  :data:`INLINE_WAIT_SECONDS`, or ``None`` (the server asked for more than we
  wait), raises :class:`Defer`: the item stays ``pending`` for reconcile,
  which re-sends it no earlier than the wait (``next_attempt_at``). A
  Retry-After beyond :data:`MAX_RETRY_AFTER_SECONDS` fails the item instead.
* **Permanent** - an unsafe URL, too large, a content encoding, any other 4xx,
  a protocol error (a broken redirect or framing: one try), anything
  unexpected: :class:`Fail`. :data:`MAX_ATTEMPTS` caps an item's lifetime.

Every hop holds a limiter slot for its own host: the first URL's, then each
redirect target's (:class:`_HopSlot`).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AbstractAsyncContextManager
from typing import Any, Final

import httpx

from sm_images.imports.errors import FetchError, FetchTimeoutError
from sm_images.imports.fetch import safe_stream
from sm_images.imports.rate_limit import (
    SlotLimiter,
    backoff,
    is_retryable_status,
    retry_after_seconds,
)
from sm_images.imports.url_safety import UnsafeURLError

__all__ = [
    "INLINE_ATTEMPTS",
    "INLINE_WAIT_SECONDS",
    "MAX_ATTEMPTS",
    "MAX_RETRY_AFTER_SECONDS",
    "RETRY_AFTER_TOO_LONG",
    "Defer",
    "Fail",
    "Stop",
    "fetch_with_retries",
]

logger = logging.getLogger(__name__)

INLINE_ATTEMPTS: Final = 3
INLINE_WAIT_SECONDS: Final = 30.0
MAX_ATTEMPTS: Final = 8
MAX_RETRY_AFTER_SECONDS: Final = 86400
"""The longest Retry-After an item is deferred for; beyond it the item fails
:data:`RETRY_AFTER_TOO_LONG` rather than sitting pending for days."""
RETRY_AFTER_TOO_LONG: Final = "retry_after_too_long"
_sleep = asyncio.sleep


class Stop(Exception):  # noqa: N818 - a signal
    def __init__(self, code: str, attempts: int, delay: float | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.attempts = attempts
        self.delay = delay


class Defer(Stop):
    """Retry later (reconcile re-dispatches the pending item), not before
    ``delay`` seconds when known - the server's Retry-After, or our backoff."""


class Fail(Stop):
    """Permanent: the item fails."""


def _classify(exc: BaseException) -> tuple[bool, str, httpx.Response | None]:
    """``(retryable, code, response)`` for a failed fetch."""
    if isinstance(exc, UnsafeURLError):
        return False, "unsafe_url", None
    if isinstance(exc, FetchTimeoutError):
        return True, "timeout", None
    if isinstance(exc, FetchError):
        return False, exc.code, None
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return is_retryable_status(status), f"http_{status}", exc.response
    if isinstance(exc, httpx.RemoteProtocolError):
        return False, "protocol_error", None  # a broken redirect or framing: one try
    if isinstance(exc, httpx.TransportError):
        return True, "transport_error", None
    # Anything else is a fault nobody can retry away; failing the item keeps
    # reconcile from re-sending it forever.
    logger.warning("images.import.fetch_unexpected", exc_info=exc)
    return False, "fetch_failed", None


class _HopSlot:
    """The limiter slot of the hop being fetched. A redirect gives up the
    previous hop's slot *before* waiting for the next host's - holding one
    while waiting for another could deadlock a batch whose every fetch
    redirects - so each hop counts against its own host's cap."""

    def __init__(self, limiter: SlotLimiter) -> None:
        self._limiter = limiter
        self._held: AbstractAsyncContextManager[None] | None = None

    async def enter(self, url: str) -> None:
        await self.leave()
        held = self._limiter.slot(url)
        await held.__aenter__()
        self._held = held

    async def leave(self) -> None:
        held, self._held = self._held, None
        if held is not None:
            await held.__aexit__(None, None, None)


async def _fetch(url: str, settings: Any, limiter: SlotLimiter) -> bytes:
    hop = _HopSlot(limiter)
    await hop.enter(url)
    try:
        parts = [
            c
            async for c in safe_stream(
                url,
                max_bytes=settings.max_image_bytes,
                timeout=settings.download_timeout,
                on_redirect=lambda target: hop.enter(str(target)),
            )
        ]
    finally:
        await hop.leave()
    return b"".join(parts)


async def fetch_with_retries(
    url: str, limiter: SlotLimiter, settings: Any, prior: int
) -> tuple[bytes, int]:
    """The body, and how many attempts it took; raises ``Fail`` or ``Defer``."""
    for attempt in range(INLINE_ATTEMPTS):
        try:
            return await _fetch(url, settings, limiter), attempt + 1
        except Exception as exc:
            retryable, code, response = _classify(exc)
            made = attempt + 1
            if not retryable or prior + made >= MAX_ATTEMPTS:
                raise Fail(code, made) from exc
            asked = retry_after_seconds(response)
            if asked is not None and asked > MAX_RETRY_AFTER_SECONDS:
                raise Fail(RETRY_AFTER_TOO_LONG, made) from exc
            wait = backoff(response, prior + attempt)
            if wait is None or wait > INLINE_WAIT_SECONDS or made == INLINE_ATTEMPTS:
                raise Defer(code, made, asked if wait is None else wait) from exc
            await _sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover
