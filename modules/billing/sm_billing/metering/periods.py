"""Which billing period a counter counts against.

The subscription's own period when the provider gave us one and ``now`` is
inside it; otherwise (no subscription, the default plan, a manual
assignment, or a period gone stale after a missed webhook) the UTC calendar
month containing ``now``. Rollover needs no job: a new period is a new
``period_start``, so its first call starts a fresh counter.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sm_billing.constants import ENTITLED_STATUSES

if TYPE_CHECKING:
    from sm_billing.models import Subscription


def as_utc(value: datetime) -> datetime:
    """Aware UTC. SQLite hands ``DateTime(timezone=True)`` back naive (it was
    stored as UTC); Postgres hands it back aware in the session's zone."""
    return value.replace(tzinfo=UTC) if value.utcoffset() is None else value.astimezone(UTC)


def calendar_month(now: datetime) -> tuple[datetime, datetime]:
    """``[first of the month, first of the next)`` in UTC."""
    now = as_utc(now)
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    if now.month == 12:
        return start, datetime(now.year + 1, 1, 1, tzinfo=UTC)
    return start, datetime(now.year, now.month + 1, 1, tzinfo=UTC)


def provider_period(sub: Subscription | None, now: datetime) -> tuple[datetime, datetime] | None:
    """The subscription's own period, when it is in force and ``now`` is inside it."""
    if (
        sub is not None
        and sub.status in ENTITLED_STATUSES
        and sub.current_period_start is not None
        and sub.current_period_end is not None
    ):
        start, end = as_utc(sub.current_period_start), as_utc(sub.current_period_end)
        if start <= now < end:
            return start, end
    return None


def current_period(sub: Subscription | None, now: datetime) -> tuple[datetime, datetime]:
    """The ``[start, end)`` a call at ``now`` counts against; ``end`` is exclusive."""
    now = as_utc(now)
    return provider_period(sub, now) or calendar_month(now)


def _back_one(start: datetime, *, years: int) -> datetime:
    """``start`` one month (or ``years`` years) earlier, the day clamped to
    the shorter month (Mar 31 -> Feb 28)."""
    if years:
        year, month = start.year - years, start.month
    elif start.month == 1:
        year, month = start.year - 1, 12
    else:
        year, month = start.year, start.month - 1
    day = start.day
    while True:
        try:
            return start.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1


def previous_period(sub: Subscription | None, now: datetime) -> tuple[datetime, datetime]:
    """The period immediately before ``current_period(sub, now)``.

    One subscription interval back from the provider's start when the
    provider's period is the current one, else the previous calendar month.
    Its end is always the current period's start.
    """
    now = as_utc(now)
    provider = provider_period(sub, now)
    if provider is None:
        start = calendar_month(now)[0]
        return calendar_month(start - timedelta(microseconds=1))[0], start
    start = provider[0]
    yearly = sub is not None and sub.interval == "year"
    return _back_one(start, years=1 if yearly else 0), start
