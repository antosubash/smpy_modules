"""When a subscription is fetched next. Pure: a clock and a random source go in.

The interval is the subscription's own or the install-wide setting, kept between
``SUBSCRIPTION_MIN_REFRESH_MINUTES`` and ``SUBSCRIPTION_MAX_REFRESH_MINUTES`` wherever it is read
(a third party's server is never hammered, whatever is stored). A server that says how long its
answer may be cached (``Cache-Control: max-age``) or when to come back (``Retry-After``) is
believed, up to a day. A failure backs off exponentially and every delay is jittered by 10 per
cent so subscriptions to one server do not fall in step. Ten failures in a row, or ``gone`` or an
unreadable address at once, disable the subscription: it is fetched again only when someone asks.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from sm_events.core import constants

__all__ = ["after_failure", "after_success", "effective_minutes"]

_JITTER = 0.1
_DISABLE_AT_ONCE = frozenset({"gone", "url_unreadable"})
_CEILING = constants.SUBSCRIPTION_MAX_BACKOFF.total_seconds()


def effective_minutes(sub_minutes: int | None, setting_minutes: int) -> int:
    wanted = sub_minutes if sub_minutes is not None else setting_minutes
    return max(
        constants.SUBSCRIPTION_MIN_REFRESH_MINUTES,
        min(constants.SUBSCRIPTION_MAX_REFRESH_MINUTES, wanted),
    )


def _jittered(seconds: float, rng: random.Random) -> timedelta:
    return timedelta(seconds=seconds * rng.uniform(1 - _JITTER, 1 + _JITTER))


def after_success(
    now: datetime, minutes: int, rng: random.Random, *, max_age: int | None = None
) -> datetime:
    """The next fetch after a 200 or a 304: the interval, or longer when the server's own
    ``max-age`` says so (never shorter, never beyond a day)."""
    delay = _jittered(float(minutes * 60), rng)
    if max_age:
        delay = max(delay, timedelta(seconds=min(max_age, _CEILING)))
    return now + delay


def after_failure(
    now: datetime,
    minutes: int,
    failures: int,
    code: str,
    rng: random.Random,
    *,
    retry_after: int | None = None,
) -> tuple[datetime, str]:
    """``(next_fetch_at, status)`` after the ``failures``-th failure in a row (this one
    included). ``status`` is ``disabled`` at ten failures or at once for ``gone`` and an
    unreadable address, else ``error``."""
    seconds = min(minutes * 60 * 2 ** max(failures - 1, 0), _CEILING)
    delay = _jittered(seconds, rng)
    if retry_after:  # a server's own request is a floor, never shortened by jitter
        delay = max(delay, timedelta(seconds=min(retry_after, _CEILING)))
    disabled = failures >= constants.SUBSCRIPTION_MAX_FAILURES or code in _DISABLE_AT_ONCE
    return now + delay, "disabled" if disabled else "error"
