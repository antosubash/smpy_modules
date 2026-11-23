"""The rules a save and a trigger share: what a save carries, who may show what publicly, and
when a fetch may start (:func:`fetch_wait`, the one decision every trigger asks)."""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from sm_events.core import constants
from sm_events.core.errors_subscriptions import (
    SubscriptionNotPublicCalendar,
    SubscriptionPublishRequired,
)
from sm_events.core.settings import EventsSettings
from sm_events.feeds.subscriptions import urls, validate
from sm_events.models import Calendar, Subscription, Visibility

__all__ = [
    "Context",
    "check_public",
    "fetch_wait",
    "live",
    "make_due",
    "recheck_public",
    "same_address",
]


class Context:
    """What a save needs beyond the principal: settings, the saver's rights and this site's own
    host names (for the own-feed refusal)."""

    def __init__(
        self,
        settings: EventsSettings,
        *,
        is_manager: bool,
        can_publish: bool,
        own_hosts: Collection[str] = (),
        public_prefix: str = "",
    ) -> None:
        self.settings, self.is_manager, self.can_publish = settings, is_manager, can_publish
        self.own_hosts, self.public_prefix = own_hosts, public_prefix


def check_public(public: bool, calendar: Calendar, ctx: Context) -> None:
    if not public:
        return
    if not ctx.can_publish:
        raise SubscriptionPublishRequired
    if calendar.visibility != Visibility.PUBLIC.value:
        raise SubscriptionNotPublicCalendar


async def live(db: Any, calendar_id: uuid.UUID) -> list[Subscription]:
    stmt = select(Subscription).where(Subscription.calendar_id == calendar_id)  # type: ignore[arg-type]
    return list((await db.execute(stmt.order_by(Subscription.label, Subscription.id))).scalars())  # type: ignore[arg-type]


def same_address(held: list[Subscription], url: str, *, skip: uuid.UUID | None = None) -> bool:
    for sub in held:
        if sub.id == skip:
            continue
        try:
            if urls.unseal(sub.url_enc) == url:
                return True
        except urls.UrlUnreadable:
            continue  # an unreadable one cannot be compared: it never blocks a new address
    return False


def fetch_wait(sub: Subscription, now: datetime) -> timedelta:
    """How long until a fetch of ``sub`` may start: the one decision every trigger asks (refresh
    now, resume, a new address). The floor since the last attempt, an unexpired lease (an
    in-flight fetch finishes; the new work is due after it) and, for a paused subscription, the
    floor since it was paused (so pause and resume cannot be looped into fetches)."""
    floor = timedelta(seconds=constants.SUBSCRIPTION_REFRESH_NOW_SECONDS)
    waits = [timedelta(0)]
    if sub.last_fetched_at is not None:
        waits.append(sub.last_fetched_at + floor - now)
    if sub.lease_until is not None and sub.lease_until > now:
        waits.append(sub.lease_until - now)
    if sub.status == "paused":
        waits.append(sub.updated_at + floor - now)
    return max(waits)


def make_due(sub: Subscription, now: datetime) -> None:
    """Back to ``pending`` and due once ``fetch_wait`` allows. Never touches a lease."""
    wait = fetch_wait(sub, now)
    sub.status, sub.error_code, sub.last_http_status = "pending", None, None
    sub.consecutive_failures, sub.next_fetch_at = 0, now + wait


def recheck_public(sub: Subscription, ctx: Context) -> None:
    """The stored address, judged as a public one (no internal exception)."""
    try:
        current = urls.unseal(sub.url_enc)
    except urls.UrlUnreadable:
        return  # nothing to judge; the worker reports it
    validate.check_url_for_save(
        current,
        settings=ctx.settings,
        is_manager=False,
        own_hosts=ctx.own_hosts,
        public_prefix=ctx.public_prefix,
    )
