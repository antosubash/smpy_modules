"""The SQL of the external read: which subscriptions, and which items meet a window.

Two statements however many subscriptions and items there are. One-off items are ordered by
start and limited; series are limited too (the caller expands them lazily, never past the
window). ``span_start`` / ``span_end`` are the prefilter: the earliest and latest instant an item
can touch (an endless rule has no end), so one predicate serves both kinds. A moved instance
stretches its item's span, which is how an instance moved into the window is found.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlmodel import col

from sm_events.core import constants
from sm_events.models import ExternalItem, Subscription

__all__ = ["items_in_window", "live_subscriptions"]


async def live_subscriptions(
    db: Any, calendar_ids: Collection[uuid.UUID], *, public_only: bool
) -> list[Subscription]:
    """The subscriptions of these calendars (soft-deleted ones are filtered by the framework),
    paused, failing and disabled ones included: their cached items stay on the calendar."""
    if not calendar_ids:
        return []
    stmt = select(Subscription).where(col(Subscription.calendar_id).in_(calendar_ids))
    if public_only:
        stmt = stmt.where(col(Subscription.public).is_(True))
    stmt = stmt.order_by(col(Subscription.label), col(Subscription.id)).limit(
        constants.SUBSCRIPTIONS_PER_TENANT
    )
    return list((await db.execute(stmt)).scalars().all())


async def items_in_window(
    db: Any,
    subscription_ids: Collection[uuid.UUID],
    start: datetime,
    end: datetime,
    *,
    limit: int,
    public_only: bool,
) -> tuple[list[ExternalItem], list[ExternalItem], bool]:
    """``(one-offs, series, series_truncated)`` meeting ``[start, end)``: one-offs by start,
    at most ``limit + 1``; series at most ``SERIES_FETCH_MAX``, ``True`` when there were more."""
    if not subscription_ids:
        return [], [], False
    base = select(ExternalItem).where(
        col(ExternalItem.subscription_id).in_(subscription_ids),
        col(ExternalItem.span_start) < end,
        or_(col(ExternalItem.span_end).is_(None), col(ExternalItem.span_end) > start),
    )
    if public_only:
        base = base.where(col(ExternalItem.private_class).is_(False))
    one_offs = (
        (
            await db.execute(
                base.where(col(ExternalItem.rrule).is_(None))
                .order_by(col(ExternalItem.starts_at), col(ExternalItem.id))
                .limit(limit + 1)
            )
        )
        .scalars()
        .all()
    )
    series = (
        (
            await db.execute(
                base.where(col(ExternalItem.rrule).is_not(None))
                .order_by(col(ExternalItem.id))
                .limit(constants.SERIES_FETCH_MAX + 1)
            )
        )
        .scalars()
        .all()
    )
    return (
        list(one_offs),
        list(series[: constants.SERIES_FETCH_MAX]),
        len(series) > constants.SERIES_FETCH_MAX,
    )
