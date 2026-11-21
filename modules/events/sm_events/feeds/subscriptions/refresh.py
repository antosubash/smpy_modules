"""One pass of the beat over the external calendars that have fallen due.

A platform pass (no tenant bound by the caller), safe to run twice, late or never.

1. **One narrow read** lists the oldest due subscriptions of every tenant (live, not deleted, on
   a calendar that is not in the trash, not under an unexpired lease), inside the framework's
   ``all_tenants()`` (which strict isolation asks for) and tagged for events' own guard. They are
   then taken in turns by tenant: the one that has used the fewest seconds of the tick goes next.
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
from sqlalchemy import func, select

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


def _due_stmt(now: datetime) -> Any:
    """The tick's candidates, chosen fairly in SQL (so no tenant, member, calendar or host can fill
    the window however much is overdue). Over the due, unleased feeds of calendars not in the trash:
    1. per (tenant, host) the first ``SUBSCRIPTION_TICK_PER_HOST`` (a provider's feeds are served
       several at a time, never all of them);
    2. within a tenant, members in turn (every member's first feed before anyone's second) and,
       within a member, calendars in turn; a feed that has been slow after the others;
    3. across tenants, every tenant's first rows before anyone's second, at most
       ``SUBSCRIPTION_TICK_CANDIDATES`` rows. How many of them are fetched is the budgets' job."""
    subs = Subscription.__table__
    cals = Calendar.__table__
    by_age = (subs.c.next_fetch_at, subs.c.id)
    base = (
        select(
            subs.c.tenant_id,
            subs.c.id,
            subs.c.next_fetch_at,
            subs.c.slow_count,
            subs.c.created_by,
            func.row_number()
            .over(
                partition_by=(subs.c.tenant_id, subs.c.url_host),
                order_by=(subs.c.slow_count, *by_age),
            )
            .label("in_host"),
            func.row_number()
            .over(
                partition_by=(subs.c.tenant_id, subs.c.created_by, subs.c.calendar_id),
                order_by=(subs.c.slow_count, *by_age),
            )
            .label("in_calendar"),
        )
        .select_from(subs.join(cals, cals.c.id == subs.c.calendar_id))
        .where(lease.due(now), cals.c.is_deleted.is_(False))
        .subquery("base")
    )
    kept = (
        select(
            base.c.tenant_id,
            base.c.id,
            base.c.next_fetch_at,
            base.c.slow_count,
            func.row_number()
            .over(
                partition_by=(base.c.tenant_id, base.c.created_by),
                order_by=(base.c.slow_count, base.c.in_calendar, base.c.next_fetch_at, base.c.id),
            )
            .label("owner_turn"),
        )
        .where(base.c.in_host <= constants.SUBSCRIPTION_TICK_PER_HOST)
        .subquery("kept")
    )
    ranked = select(
        kept.c.tenant_id,
        kept.c.id,
        kept.c.next_fetch_at,
        kept.c.slow_count,
        func.row_number()
        .over(
            partition_by=kept.c.tenant_id,
            order_by=(kept.c.owner_turn, kept.c.slow_count, kept.c.next_fetch_at, kept.c.id),
        )
        .label("in_tenant"),
    ).subquery("ranked")
    return (
        select(ranked.c.tenant_id, ranked.c.id, ranked.c.slow_count)
        .order_by(ranked.c.in_tenant, ranked.c.next_fetch_at, ranked.c.id)
        .limit(constants.SUBSCRIPTION_TICK_CANDIDATES)
        .execution_options(include_deleted=True)
    )


async def _due(
    factory: Any, now: datetime
) -> tuple[dict[str, list[tuple[uuid.UUID, int]]], set[str]]:
    """``({tenant: [(subscription id, slow score), ...]}, slow tenants)``: each tenant's own order,
    tenants in the rotation that starts at a different one every minute, and the tenants that have
    a feed with a slow score (it just answered slowly: those feed no longer due, so only the
    tenant, not its due rows, still shows it)."""
    subs = Subscription.__table__
    slow_stmt = (
        select(subs.c.tenant_id)
        .where(subs.c.slow_count > 0, subs.c.is_deleted.is_(False))
        .distinct()
    )
    with framework_all_tenants():
        async with factory() as session:
            rows = [
                (str(t), i, int(slow))
                for t, i, slow in (await session.execute(all_tenants(_due_stmt(now)))).all()
            ]
            slow_tenants = {
                str(t) for t in (await session.execute(all_tenants(slow_stmt))).scalars()
            }
            await finalize_session(session)
    queues: dict[str, list[tuple[uuid.UUID, int]]] = {}
    for tenant in order_tenants(sorted({r[0] for r in rows if valid_tenant(r[0])}), now):
        queues[tenant] = []
    for tenant, sid, slow in rows:
        if tenant in queues:
            queues[tenant].append((sid, slow))
    return queues, slow_tenants & set(queues)


_SLOW_HEAD_START = 2.0 * constants.SUBSCRIPTION_SLOW_SECONDS
_MIN_CHARGE = 1.0
"""Seconds charged to a tenant for a fetch even when it was faster: so tenants with cheap fetches
still take turns instead of one draining its queue first."""


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
    "lease_lost"}`` (and ``unavailable`` when no secret key could be read).

    The tick's budget (fetches, bytes, seconds) is shared by the tenants that have work: the one
    that has used the fewest seconds goes next (a fetch counts at least a second), so tenants take
    equal shares of the time, a tenant that is slow uses up its own share and not another's, and
    one that is alone, or whose queue is short, leaves the rest to the others."""
    fetcher = fetcher or fetch_feed
    rng = rng or _new_rng()
    owner = uuid.uuid4().hex
    deadline = clock() + constants.SUBSCRIPTION_TICK_SECONDS
    counts: Counter[str] = Counter(dict.fromkeys(COUNTS, 0))
    started = received = 0
    queues, slow_tenants = await _due(factory, now)
    # A tenant with a slow feed starts a tick as if it had already used a slow fetch's time, so
    # tenants without one are served first and it takes the rest of the share.
    used = {tenant: _SLOW_HEAD_START if tenant in slow_tenants else 0.0 for tenant in queues}
    turn = {tenant: index for index, tenant in enumerate(queues)}
    counts["tenants"] = len(queues)
    while queues:
        if (
            started >= constants.SUBSCRIPTION_TICK_FETCHES
            or received >= constants.SUBSCRIPTION_TICK_BYTES
            or deadline - clock() < _START_MARGIN
        ):
            counts["skipped_budget"] += sum(len(q) for q in queues.values())
            break
        tenant = min(queues, key=lambda t: (used[t], turn[t]))
        sid, _slow = queues[tenant].pop(0)
        if not queues[tenant]:
            del queues[tenant]
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
            used[tenant] += _MIN_CHARGE
            continue
        used[tenant] += max(done.seconds, _MIN_CHARGE)
        received += done.received
        if done.outcome == "stored":
            counts["fetched"] += 1
        elif done.outcome in ("not_modified", "failed", "lease_lost"):
            counts[done.outcome] += 1
        elif done.outcome == "deferred":
            counts["skipped_budget"] += 1  # a server just contacted: waits out its spacing
        elif done.outcome == "busy":
            counts["lease_lost"] += 1  # another worker took it first
        elif done.outcome == "unavailable":
            counts["unavailable"] += 1
            break
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
