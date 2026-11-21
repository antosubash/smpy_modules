"""The beat's budgets and fairness for external subscriptions (PR 10), split from
:mod:`sm_events.core.constants.subscriptions` (file size): how many fetches a tick makes, how it
shares them between tenants, the per-server spacing and the slow-feed score."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

__all__ = [
    "SUBSCRIPTION_LEASE",
    "SUBSCRIPTION_MAX_CONCURRENT_FETCHES",
    "SUBSCRIPTION_MAX_CONCURRENT_FETCHES_PER_TENANT",
    "SUBSCRIPTION_QUEUED_MINUTES",
    "SUBSCRIPTION_SLOW_MAX",
    "SUBSCRIPTION_SLOW_SECONDS",
    "SUBSCRIPTION_TARGET_KEPT_HOURS",
    "SUBSCRIPTION_TARGET_SPACING_SECONDS",
    "SUBSCRIPTION_TICK_BYTES",
    "SUBSCRIPTION_TICK_CANDIDATES",
    "SUBSCRIPTION_TICK_FETCHES",
    "SUBSCRIPTION_TICK_PER_HOST",
    "SUBSCRIPTION_TICK_SECONDS",
]

# The beat (Ruling 15).
SUBSCRIPTION_TICK_FETCHES: Final = 20
SUBSCRIPTION_QUEUED_MINUTES: Final = 2
"""What "refresh now" says when the fetch is queued and has not run yet: the beat takes it up on its
next minute, and a slow fetch ahead of it can add one more."""
SUBSCRIPTION_TICK_CANDIDATES: Final = 200
"""Rows one tick reads (chosen fairly in SQL: owners and calendars in turn within a tenant, a
tenant's first rows before anyone's second); the budgets below decide how many are fetched."""
SUBSCRIPTION_TICK_PER_HOST: Final = 5
"""Most subscriptions of one tenant on one address host one tick selects, so a provider's many
feeds (all calendars of one service share a host) are served several at a time, not one."""
SUBSCRIPTION_TARGET_SPACING_SECONDS: Final = 3
"""Per tenant and validated server IP: connections are at least this far apart (a fetch that is
early waits, up to this long), counted from the last connection and kept after a subscription is
deleted. The most one tenant can aim at one server is one request per spacing, 20 a minute: the
same as its write limit and as the 100 subscriptions' 300 s floors (100 / 300 s)."""
SUBSCRIPTION_TARGET_KEPT_HOURS: Final = 1
SUBSCRIPTION_SLOW_SECONDS: Final = 5
"""A fetch that takes longer is slow: its score (``slow_count``) goes up, which orders the feed
after the others and pushes its next fetch out (``SUBSCRIPTION_SLOW_MAX`` doublings at most, never
beyond ``SUBSCRIPTION_MAX_BACKOFF``); each fast success lowers it by one. Separately the tick
shares its seconds between tenants by seconds actually used, whatever any fetch's speed."""
SUBSCRIPTION_SLOW_MAX: Final = 4
SUBSCRIPTION_TICK_BYTES: Final = 50 * 1024 * 1024
SUBSCRIPTION_TICK_SECONDS: Final = 45
SUBSCRIPTION_LEASE: Final = timedelta(minutes=2)
SUBSCRIPTION_MAX_CONCURRENT_FETCHES_PER_TENANT: Final = 2
"""One tenant's share of those slots (a quarter): hung feeds of one tenant cannot hold the pool."""
SUBSCRIPTION_MAX_CONCURRENT_FETCHES: Final = 8
"""Install-wide ceiling on subscriptions leased (so being fetched) at once, whatever the number of
beats and workers; the excess waits for the next tick. Counted in the claim's own statement, so
it can overshoot by at most the number of claims racing at that instant."""
