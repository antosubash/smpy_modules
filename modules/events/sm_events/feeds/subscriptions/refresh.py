"""One pass of the beat over the external calendars that have fallen due.

A platform pass (no tenant bound by the caller), safe to run twice, late or never.

1. **One narrow read** lists the oldest due subscriptions of every tenant (live, not deleted, on
   a calendar that is not in the trash, not under an unexpired lease), inside the framework's
   ``all_tenants()`` (which strict isolation asks for) and tagged for events' own guard. They are
   then served tenant by tenant, in a rotation that starts elsewhere every minute.
2. **Per subscription** (the same pass for the beat and for "refresh now"): *claim* (compare and
   set, committed), open the address, *fetch with no session open*, then, in one transaction
   fenced on the lease, store the feed or record the failure, release the lease and commit. A
   fetch that outlives its lease cannot store; a crashed one leaves a lease that simply expires.
3. **Bounds.** At most ``SUBSCRIPTION_TICK_FETCHES`` fetches, ``SUBSCRIPTION_TICK_BYTES`` received
   and ``SUBSCRIPTION_TICK_SECONDS`` of wall clock, a fetch starting only with 30 s of that left;
   fetches are sequential, so one worker is one outbound request at a time. What does not fit
   waits for the next tick.
4. **Failure** is one code from a closed set, recorded with the backoff of ``schedule``; the old
   items stay. A tenant (or a subscription) whose work raises is logged by class and counted and
   does not stop the others. Only counts reach the log; an address never does.
"""

from __future__ import annotations

import logging
import random
import time
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from typing import Any

from simple_module_db import all_tenants as framework_all_tenants
from simple_module_db import finalize_session
from sqlalchemy import func, or_, select

from sm_events.core import constants
from sm_events.core.clock import utcnow
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import all_tenants, valid_tenant
from sm_events.feeds.subscriptions import lease
from sm_events.feeds.subscriptions.attempt import attempt
from sm_events.feeds.subscriptions.fetch import fetch_feed
from sm_events.models import Calendar, Subscription
from sm_events.reminders.tick import order_tenants

__all__ = ["COUNTS", "refresh_async", "refresh_one_async"]

logger = logging.getLogger(__name__)

COUNTS = ("tenants", "fetched", "not_modified", "failed", "skipped_budget", "lease_lost")
_START_MARGIN = 30.0


def _new_rng() -> random.Random:
    return random.Random()  # noqa: S311 - schedule jitter, not a secret


def _stored_settings() -> EventsSettings:
    """The stored settings as a worker reads them (synchronous, cached for 30 s)."""
    from background_tasks import settings_for

    return settings_for(EventsSettings, constants.PACKAGE, ttl=30)


def rotate(rows: list[Any], now: datetime) -> list[Any]:
    """Tenants in turn, starting at a different one every minute (the reminders tick's rotation),
    each tenant's rows together and in its own order (already limited to its fair share in SQL):
    a tenant's cheap feeds are not queued behind another's slow one, and a budget that runs out
    mid-tick falls on the tenants whose turn came last."""
    by_tenant: dict[str, list[Any]] = {}
    for tenant in order_tenants(sorted({row[0] for row in rows}), now):
        by_tenant[tenant] = []
    for row in rows:
        by_tenant[row[0]].append(row)
    return [row for group in by_tenant.values() for row in group]


def _due_stmt(now: datetime) -> Any:
    """The tick's candidates, chosen fairly in SQL (so no tenant, calendar or host can fill the
    window however much is overdue). Three steps over the due, unleased, floor-free rows:
    1. per (tenant, calendar), the oldest ``SUBSCRIPTION_TICK_PER_CALENDAR``, and per (tenant,
       host) the oldest one (a host is fetched once per tick);
    2. per tenant, calendars in turn (first rows of every calendar before any second row), a feed
       that has been slow after the others, then the oldest: the first
       ``SUBSCRIPTION_TICK_PER_TENANT``;
    3. oldest first, at most twice the fetches one tick can make."""
    subs = Subscription.__table__
    cals = Calendar.__table__
    by_age = (subs.c.next_fetch_at, subs.c.id)
    base = (
        select(
            subs.c.tenant_id,
            subs.c.id,
            subs.c.next_fetch_at,
            subs.c.slow_count,
            func.row_number()
            .over(partition_by=(subs.c.tenant_id, subs.c.calendar_id), order_by=by_age)
            .label("in_calendar"),
            func.row_number()
            .over(partition_by=(subs.c.tenant_id, subs.c.url_host), order_by=by_age)
            .label("in_host"),
        )
        .select_from(subs.join(cals, cals.c.id == subs.c.calendar_id))
        .where(lease.due(now), lease.host_free(now), cals.c.is_deleted.is_(False))
        .subquery("base")
    )
    kept = (
        select(
            base.c.tenant_id,
            base.c.id,
            base.c.next_fetch_at,
            func.row_number()
            .over(
                partition_by=base.c.tenant_id,
                order_by=(base.c.slow_count, base.c.in_calendar, base.c.next_fetch_at, base.c.id),
            )
            .label("in_tenant"),
        )
        .where(
            base.c.in_calendar <= constants.SUBSCRIPTION_TICK_PER_CALENDAR,
            or_(base.c.in_host == 1, base.c.in_host.is_(None)),
        )
        .subquery("kept")
    )
    return (
        select(kept.c.tenant_id, kept.c.id)
        .where(kept.c.in_tenant <= constants.SUBSCRIPTION_TICK_PER_TENANT)
        .order_by(kept.c.next_fetch_at, kept.c.id)
        .limit(2 * constants.SUBSCRIPTION_TICK_FETCHES)
        .execution_options(include_deleted=True)
    )


async def _due(factory: Any, now: datetime) -> list[tuple[str, uuid.UUID]]:
    with framework_all_tenants():
        async with factory() as session:
            rows = [
                (str(t), i) for t, i in (await session.execute(all_tenants(_due_stmt(now)))).all()
            ]
            await finalize_session(session)
    return rotate([row for row in rows if valid_tenant(row[0])], now)


async def refresh_async(
    factory: Any,
    *,
    now: datetime,
    settings: EventsSettings,
    fetcher: Callable[..., Any] | None = None,
    rng: random.Random | None = None,
    clock: Callable[[], float] = time.monotonic,
    utc_now: Callable[[], datetime] = utcnow,
) -> dict[str, int]:
    """One tick; ``{"tenants", "fetched", "not_modified", "failed", "skipped_budget",
    "lease_lost"}`` (and ``unavailable`` when no secret key could be read)."""
    fetcher = fetcher or fetch_feed
    rng = rng or _new_rng()
    owner = uuid.uuid4().hex
    deadline = clock() + constants.SUBSCRIPTION_TICK_SECONDS
    counts: Counter[str] = Counter(dict.fromkeys(COUNTS, 0))
    started = received = 0
    tenants: set[str] = set()
    slow_tenants: set[str] = set()  # a tenant whose fetch was slow waits for the next tick
    for tenant, sid in await _due(factory, now):
        tenants.add(tenant)
        if (
            started >= constants.SUBSCRIPTION_TICK_FETCHES
            or received >= constants.SUBSCRIPTION_TICK_BYTES
            or deadline - clock() < _START_MARGIN
            or tenant in slow_tenants
        ):
            counts["skipped_budget"] += 1
            continue
        started += 1
        try:
            done = await attempt(
                factory,
                tenant,
                sid,
                owner=owner,
                now=now,
                settings=settings,
                fetcher=fetcher,
                rng=rng,
                utc_now=utc_now,
                clock=clock,
            )
        except Exception as exc:  # one tenant's failure never stops the rest
            logger.warning(
                "events.refresh_subscriptions: a subscription failed (%s)", type(exc).__name__
            )
            counts["failed"] += 1
            continue
        received += done.received
        if done.seconds > constants.SUBSCRIPTION_SLOW_SECONDS:
            slow_tenants.add(tenant)
        if done.outcome == "stored":
            counts["fetched"] += 1
        elif done.outcome in ("not_modified", "failed", "lease_lost"):
            counts[done.outcome] += 1
        elif done.outcome == "busy":
            counts["lease_lost"] += 1  # another worker took it first
        elif done.outcome == "unavailable":
            counts["unavailable"] += 1
            break
    counts["tenants"] = len(tenants)
    logger.info("events.refresh_subscriptions: %s", dict(counts))
    return dict(counts)


async def refresh_one_async(
    factory: Any,
    *,
    tenant_id: str,
    subscription_id: uuid.UUID,
    now: datetime,
    settings: EventsSettings,
    fetcher: Callable[..., Any] | None = None,
    rng: random.Random | None = None,
    utc_now: Callable[[], datetime] = utcnow,
) -> str:
    """One subscription, on demand: ``stored``, ``not_modified``, ``failed``, ``busy`` (not due
    or under someone's lease), ``lease_lost`` or ``unavailable``. The same guarded fetch."""
    done = await attempt(
        factory,
        tenant_id,
        subscription_id,
        owner=uuid.uuid4().hex,
        now=now,
        settings=settings,
        fetcher=fetcher or fetch_feed,
        rng=rng or _new_rng(),
        utc_now=utc_now,
    )
    return done.outcome
