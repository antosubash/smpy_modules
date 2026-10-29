"""Courtesy toward remote hosts: :class:`DomainLimiter` and :func:`backoff`.

``DomainLimiter`` is in-process (asyncio). The portal's ``domain_rate_limiter``
keeps its slots in Redis because each Celery download runs its own event loop,
so a process-local semaphore limits only what shares one loop. Callers depend on
the :class:`SlotLimiter` protocol, so a cross-worker implementation can replace
this one without touching them.

``backoff`` ports ``download_retry`` and fixes its two gaps: Retry-After given
as an HTTP date is honoured, and a server delay is never cut short - one longer
than :data:`MAX_BACKOFF_SECONDS` yields ``None`` (defer) instead of an early
retry.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Final, Protocol

import httpx

__all__ = [
    "MAX_BACKOFF_SECONDS",
    "RETRY_AFTER_CEILING",
    "DomainLimiter",
    "SlotLimiter",
    "backoff",
    "domain_of",
    "is_retryable_status",
    "retry_after_seconds",
]

MAX_BACKOFF_SECONDS: Final = 300
RETRY_AFTER_CEILING: Final = 2 * 86400.0
"""The most a Retry-After is read as: a larger ask (a 400-digit delta, a date in
the year 9999) is this, so nothing downstream overflows a ``timedelta``."""
_DELTA_DIGITS_MAX: Final = 9
_BASE_SECONDS: Final = 1.0
_JITTER: Final = 0.25
_MAX_EXPONENT: Final = 16
_RETRYABLE: Final = frozenset({408, 429})


def domain_of(url: str) -> str:
    """``url``'s host as one key per host: IDNA (punycode), lowercased, without a
    trailing dot - or ``"unknown"``."""
    try:
        host = httpx.URL(url).raw_host.decode("ascii")
    except (httpx.InvalidURL, TypeError, ValueError, UnicodeDecodeError):
        return "unknown"
    return host.lower().rstrip(".") or "unknown"


class SlotLimiter(Protocol):
    """What a download needs from a limiter; a Redis-backed one would fit too."""

    def slot(self, url: str) -> AbstractAsyncContextManager[None]: ...


class DomainLimiter:
    """At most ``per_domain`` fetches per host and ``total`` overall.

    The domain slot is taken first, so a waiter for a busy host holds no global
    slot while it waits and cannot starve other hosts. A domain's state is
    dropped once nobody holds or waits for it. An instance belongs to one event
    loop (asyncio primitives bind to the loop that first contends them).
    """

    def __init__(self, per_domain: int, total: int) -> None:
        if per_domain < 1 or total < 1:
            raise ValueError("per_domain and total must be at least 1")
        self._per_domain = per_domain
        self._total = asyncio.Semaphore(total)
        self._domains: dict[str, tuple[asyncio.Semaphore, list[int]]] = {}

    def tracked_domains(self) -> int:
        return len(self._domains)

    @asynccontextmanager
    async def slot(self, url: str) -> AsyncIterator[None]:
        domain = domain_of(url)
        semaphore, users = self._domains.setdefault(
            domain, (asyncio.Semaphore(self._per_domain), [0])
        )
        users[0] += 1
        try:
            async with semaphore, self._total:
                yield
        finally:
            users[0] -= 1
            if users[0] == 0:
                del self._domains[domain]


def is_retryable_status(status: int) -> bool:
    """429, 408 and every 5xx are worth another try; other 4xx are permanent."""
    return status in _RETRYABLE or status >= 500


def _utcnow() -> datetime:
    return datetime.now(UTC)


def retry_after_seconds(response: httpx.Response | None) -> float | None:
    """Retry-After as seconds (delta or HTTP date; a past date is 0), at most
    :data:`RETRY_AFTER_CEILING`, or ``None``."""
    if response is None:
        return None
    raw = response.headers.get("retry-after", "").strip()
    if not raw:
        return None
    if raw.isdigit():
        if len(raw) > _DELTA_DIGITS_MAX:
            return RETRY_AFTER_CEILING
        return min(float(raw), RETRY_AFTER_CEILING)
    try:
        when = parsedate_to_datetime(raw)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = (when - _utcnow()).total_seconds()
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    return min(max(0.0, seconds), RETRY_AFTER_CEILING)


def backoff(response: httpx.Response | None, attempt: int) -> float | None:
    """Seconds to wait before retry ``attempt + 1``, or ``None`` to defer.

    With a Retry-After the wait is at least what the server asked (jitter only
    adds), capped at :data:`MAX_BACKOFF_SECONDS`; a longer ask returns ``None``
    so the caller defers the item rather than retrying early. Without one it is
    exponential (1 s, 2 s, 4 s, ...) with jitter, capped likewise.
    """
    asked = retry_after_seconds(response)
    if asked is not None:
        if asked > MAX_BACKOFF_SECONDS:
            return None
        return min(asked * (1 + random.uniform(0, _JITTER)), MAX_BACKOFF_SECONDS)
    delay = _BASE_SECONDS * 2 ** min(max(attempt, 0), _MAX_EXPONENT)
    return min(delay * (1 + random.uniform(0, _JITTER)), MAX_BACKOFF_SECONDS)
