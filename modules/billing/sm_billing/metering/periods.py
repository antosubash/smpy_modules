"""Which billing period a counter counts against.

The subscription's own period when the provider gave us one and ``now`` is
inside it; otherwise (no subscription, the default plan, a manual
assignment, or a period gone stale after a missed webhook) the UTC calendar
month containing ``now``. Rollover needs no job: a new period is a new
``period_start``, so its first call starts a fresh counter.
"""

from __future__ import annotations

from datetime import UTC, datetime
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


def current_period(sub: Subscription | None, now: datetime) -> tuple[datetime, datetime]:
    """The ``[start, end)`` a call at ``now`` counts against; ``end`` is exclusive."""
    now = as_utc(now)
    if (
        sub is not None
        and sub.status in ENTITLED_STATUSES
        and sub.current_period_start is not None
        and sub.current_period_end is not None
    ):
        start, end = as_utc(sub.current_period_start), as_utc(sub.current_period_end)
        if start <= now < end:
            return start, end
    return calendar_month(now)
