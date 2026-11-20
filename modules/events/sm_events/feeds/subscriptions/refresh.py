"""One pass of the beat over the external calendars that have fallen due.

A platform pass (no tenant bound by the caller), safe to run twice, late or never.

1. **One narrow read** lists the oldest due subscriptions of every tenant (live, not deleted, on
   a calendar that is not in the trash, not under an unexpired lease), inside the framework's
   ``all_tenants()`` (which strict isolation asks for) and tagged for events' own guard. They are
   then served round-robin across tenants, so a busy tenant cannot starve another.
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
from itertools import zip_longest
from typing import Any

from simple_module_db import all_tenants as framework_all_tenants
from simple_module_db import finalize_session
from sqlalchemy import select

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
    """Round-robin across tenants, each tenant's own order (oldest due first) kept, starting at a
    different tenant every minute (the reminders tick's rotation), so the shared slots are
    spread fairly across ticks."""
    by_tenant: dict[str, list[Any]] = {}
    for tenant in order_tenants(sorted({row[0] for row in rows}), now):
        by_tenant[tenant] = []
    for row in rows:
        by_tenant[row[0]].append(row)
    return [row for group in zip_longest(*by_tenant.values()) for row in group if row is not None]


async def _due(factory: Any, now: datetime) -> list[tuple[str, uuid.UUID]]:
    stmt = all_tenants(
        select(Subscription.tenant_id, Subscription.id)
        .join(Calendar, Calendar.id == Subscription.calendar_id)  # type: ignore[arg-type]
        .where(lease.due(now), Calendar.is_deleted.is_(False))  # type: ignore[attr-defined]
        .order_by(Subscription.next_fetch_at, Subscription.id)  # type: ignore[arg-type]
        .limit(2 * constants.SUBSCRIPTION_TICK_FETCHES)
    )
    with framework_all_tenants():
        async with factory() as session:
            rows = [(str(t), i) for t, i in (await session.execute(stmt)).all()]
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
    for tenant, sid in await _due(factory, now):
        tenants.add(tenant)
        if (
            started >= constants.SUBSCRIPTION_TICK_FETCHES
            or received >= constants.SUBSCRIPTION_TICK_BYTES
            or deadline - clock() < _START_MARGIN
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
            )
        except Exception as exc:  # one tenant's failure never stops the rest
            logger.warning(
                "events.refresh_subscriptions: a subscription failed (%s)", type(exc).__name__
            )
            counts["failed"] += 1
            continue
        received += done.received
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
