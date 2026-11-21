"""What a response says about when to come back and why a fetch failed: small readers over an
``httpx.Response`` and the mapping from a network error to a closed failure code. No text from
the remote or from a library exception survives."""

from __future__ import annotations

import re
import ssl
from email.utils import parsedate_to_datetime
from typing import Final

import httpx

from sm_events.core.clock import utcnow
from sm_events.feeds.subscriptions import policy as url_policy
from sm_events.feeds.subscriptions.errors import FetchFailure
from sm_events.feeds.subscriptions.url_safety import UnsafeURLError

__all__ = ["failure_of", "max_age", "retry_after"]

_MAX_AGE: Final = re.compile(r"(?i)(?:^|[\s,])max-age=(\d{1,9})(?:$|[\s,;])")
_ONE_YEAR: Final = 365 * 24 * 3600


def max_age(response: httpx.Response) -> int | None:
    found = _MAX_AGE.search(response.headers.get("cache-control", ""))
    return int(found.group(1)) or None if found else None


def retry_after(response: httpx.Response) -> int | None:
    """Seconds from ``Retry-After`` (a number, or an HTTP date), or ``None`` for anything else."""
    raw = response.headers.get("retry-after", "").strip()
    if not raw:
        return None
    try:
        seconds = (
            int(raw)
            if raw.isdigit()
            else int((parsedate_to_datetime(raw) - utcnow()).total_seconds())
        )
    except (TypeError, ValueError, OverflowError):
        return None
    return seconds if 0 < seconds <= _ONE_YEAR else None


def failure_of(error: BaseException) -> FetchFailure:
    """The code for a failure of the network layer. Never keeps the exception's text."""
    if isinstance(error, TimeoutError | httpx.TimeoutException):
        return FetchFailure("timeout")
    if isinstance(error, UnsafeURLError):
        return FetchFailure(url_policy.user_code(error))
    if isinstance(error, FetchFailure):
        return error
    cause: BaseException | None = error
    for _ in range(8):  # an SSL error sits a few links down httpx's and httpcore's chain
        if isinstance(cause, ssl.SSLError):
            return FetchFailure("tls_failed")
        cause = None if cause is None else (cause.__cause__ or cause.__context__)
    return FetchFailure("connect_failed")
