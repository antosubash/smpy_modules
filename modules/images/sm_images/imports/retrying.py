"""Fetching one image URL with the import retry policy (Task 16's rules).

* **Retryable** - a transport error, the deadline, 408/429/5xx: retried with
  :func:`~sm_images.imports.rate_limit.backoff`, at most
  :data:`INLINE_ATTEMPTS` times in one go. A wait longer than
  :data:`INLINE_WAIT_SECONDS`, or ``None`` (the server asked for more than we
  wait), raises :class:`Defer`: the item stays ``pending`` for reconcile.
* **Permanent** - an unsafe URL, too large, a content encoding, any other 4xx,
  a protocol error (a broken redirect or framing: one try), anything
  unexpected: :class:`Fail`. :data:`MAX_ATTEMPTS` caps an item's lifetime.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

import httpx

from sm_images.imports.errors import FetchError, FetchTimeoutError
from sm_images.imports.fetch import safe_stream
from sm_images.imports.rate_limit import DomainLimiter, backoff, is_retryable_status
from sm_images.imports.url_safety import UnsafeURLError

__all__ = [
    "INLINE_ATTEMPTS",
    "INLINE_WAIT_SECONDS",
    "MAX_ATTEMPTS",
    "Defer",
    "Fail",
    "Stop",
    "fetch_with_retries",
]

logger = logging.getLogger(__name__)

INLINE_ATTEMPTS: Final = 3
INLINE_WAIT_SECONDS: Final = 30.0
MAX_ATTEMPTS: Final = 8
_sleep = asyncio.sleep


class Stop(Exception):  # noqa: N818 - a signal
    def __init__(self, code: str, attempts: int) -> None:
        super().__init__(code)
        self.code = code
        self.attempts = attempts


class Defer(Stop):
    """Retry later (reconcile re-dispatches the pending item)."""


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


async def _fetch(url: str, settings: Any) -> bytes:
    parts = [
        c
        async for c in safe_stream(
            url, max_bytes=settings.max_image_bytes, timeout=settings.download_timeout
        )
    ]
    return b"".join(parts)


async def fetch_with_retries(
    url: str, limiter: DomainLimiter, settings: Any, prior: int
) -> tuple[bytes, int]:
    """The body, and how many attempts it took; raises ``Fail`` or ``Defer``."""
    for attempt in range(INLINE_ATTEMPTS):
        try:
            async with limiter.slot(url):
                return await _fetch(url, settings), attempt + 1
        except Exception as exc:
            retryable, code, response = _classify(exc)
            made = attempt + 1
            if not retryable or prior + made >= MAX_ATTEMPTS:
                raise Fail(code, made) from exc
            wait = backoff(response, prior + attempt)
            if wait is None or wait > INLINE_WAIT_SECONDS or made == INLINE_ATTEMPTS:
                raise Defer(code, made) from exc
            await _sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover
