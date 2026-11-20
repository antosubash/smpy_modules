"""One subscription's pass, the same for the beat and for "refresh now".

*Claim* (compare and set, committed before anything is fetched), open the address, *fetch with no
session open*, then, in one transaction fenced on the lease, store the feed or record the failure,
release the lease and commit. A fetch that outlives its lease cannot store; a crashed one leaves a
lease that simply expires. A failure is one code from a closed set, recorded with the backoff of
:mod:`~sm_events.feeds.subscriptions.schedule`; the old items stay. Only counts and the
subscription's id reach the log, never the address.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import select

from sm_events.core import constants
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.importing.staging import effective_max_bytes
from sm_events.feeds.subscriptions import lease, schedule, store, urls
from sm_events.feeds.subscriptions.errors import FetchFailure
from sm_events.feeds.subscriptions.fetch import FetchResult
from sm_events.feeds.subscriptions.policy import effective
from sm_events.feeds.subscriptions.target_gate import TargetGate
from sm_events.models import Calendar, Subscription

__all__ = ["Attempt", "attempt"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Job:
    url_enc: str
    etag: str | None
    last_modified: str | None
    minutes: int
    calendar_tz: str
    may_use_private: bool
    public: bool
    generation: int
    """``policy_generation`` when the fetch started: the store discards a result of another."""


@dataclass(frozen=True)
class Attempt:
    outcome: str
    """``stored``, ``not_modified``, ``failed``, ``lease_lost``, ``busy`` or ``unavailable``."""
    received: int = 0
    seconds: float = 0.0
    """How long the fetch took (the beat charges a slow one to its tenant)."""


async def _claim(
    factory: Any, tenant: str, sid: uuid.UUID, owner: str, now: datetime, settings: EventsSettings
) -> _Job | None:
    """Take the lease (committed before anything is fetched) and read what the fetch needs."""
    with tenant_scope(tenant):
        async with factory() as db:
            if not await lease.claim(db, sid, owner=owner, now=now):
                await finalize_session(db)
                return None
            sub = await lease.fenced(db, sid, owner=owner, now=now)
            calendar = None
            if sub is not None:
                found = select(Calendar).where(Calendar.id == sub.calendar_id)  # type: ignore[arg-type]
                calendar = (await db.execute(found)).scalar_one_or_none()
            if sub is None or calendar is None or calendar.is_deleted:
                if sub is not None:  # the calendar went to the trash since the read: no fetch
                    await lease.release(db, sub)
                await finalize_session(db)
                return None
            job = _Job(
                sub.url_enc,
                sub.etag,
                sub.last_modified,
                schedule.effective_minutes(
                    sub.refresh_minutes, settings.subscription_refresh_minutes
                ),
                calendar.default_timezone,
                sub.may_use_private,
                sub.public,
                sub.policy_generation,
            )
            await finalize_session(db)
            return job


def fetch_policy(settings: EventsSettings, sub: Any) -> Any:
    """The one policy a fetch (and every redirect hop) runs under: internal addresses need the
    setting **and** the saver's right, and a public subscription never has them."""
    return effective(
        settings.allow_private_subscription_urls,
        may_use_private=sub.may_use_private and not sub.public,
    )


async def _fetch(
    job: _Job, settings: EventsSettings, fetcher: Callable[..., Any], gate: Any = None
) -> FetchResult | FetchFailure:
    """The guarded fetch, with no database session open. Returns a failure rather than raising
    one; a missing secret key raises (the caller stops the pass)."""
    try:
        url = urls.unseal(job.url_enc)
    except urls.UrlUnreadable:
        return FetchFailure("url_unreadable")
    try:
        return await fetcher(
            url,
            policy=fetch_policy(settings, job),
            etag=job.etag,
            last_modified=job.last_modified,
            max_bytes=effective_max_bytes(settings),
            gate=gate,
        )
    except FetchFailure as failure:
        return failure
    except Exception as exc:  # the class only: its message can quote the address
        logger.warning("events subscription fetch failed unexpectedly (%s)", type(exc).__name__)
        return FetchFailure("internal")
    finally:
        del url


def _charge_slowness(sub: Subscription, stamp: datetime, seconds: float, *, failed: bool) -> None:
    """A slow fetch (``SUBSCRIPTION_SLOW_SECONDS``) pushes the next one out, doubling each time
    in a row up to ``SUBSCRIPTION_SLOW_MAX`` and never beyond ``SUBSCRIPTION_MAX_BACKOFF``; a fast
    one resets it. A failure already backs off on its own, so only the count moves then."""
    if seconds <= constants.SUBSCRIPTION_SLOW_SECONDS:
        sub.slow_count = 0
        return
    sub.slow_count = min(sub.slow_count + 1, constants.SUBSCRIPTION_SLOW_MAX)
    if not failed and sub.next_fetch_at is not None:
        wait = (sub.next_fetch_at - stamp) * 2**sub.slow_count
        sub.next_fetch_at = stamp + min(wait, constants.SUBSCRIPTION_MAX_BACKOFF)


def _internal_code(code: str) -> str:
    if code in constants.INTERNAL_NOTHING_ANSWERED:
        return "url_unreachable"
    return code if code in constants.INTERNAL_KEPT_CODES else "not_a_calendar"


def _record_failure(
    sub: Subscription, failure: FetchFailure, job: _Job, stamp: datetime, rng: random.Random
) -> None:
    failures = sub.consecutive_failures + 1
    at, status = schedule.after_failure(
        stamp, job.minutes, failures, failure.code, rng, retry_after=failure.retry_after
    )
    sub.status, sub.error_code, sub.last_http_status = status, failure.code, failure.http_status
    if job.may_use_private and not job.public:  # an internal address: show almost nothing
        sub.error_code, sub.last_http_status = _internal_code(failure.code), None
    sub.consecutive_failures, sub.last_fetched_at, sub.next_fetch_at = failures, stamp, at


def _record_success(
    sub: Subscription, result: FetchResult, job: _Job, stamp: datetime, rng: random.Random
) -> None:
    sub.status, sub.error_code, sub.last_http_status = "ok", None, None
    sub.consecutive_failures, sub.last_fetched_at, sub.last_ok_at = 0, stamp, stamp
    sub.next_fetch_at = schedule.after_success(stamp, job.minutes, rng, max_age=result.max_age)
    if result.status == "ok":  # a 304 keeps the validators it matched
        sub.etag, sub.last_modified = result.etag, result.last_modified


async def _store(
    factory: Any,
    tenant: str,
    sid: uuid.UUID,
    owner: str,
    job: _Job,
    outcome: FetchResult | FetchFailure,
    rng: random.Random,
    utc_now: Callable[[], datetime],
    seconds: float = 0.0,
) -> Attempt:
    """Store the result (or record the failure) in one transaction fenced on the lease. A body
    is scanned and mapped first, in a thread, before any lock: an edit never waits for a parse."""
    prepared: store.Prepared | None = None
    failure: FetchFailure | None = outcome if isinstance(outcome, FetchFailure) else None
    if isinstance(outcome, FetchResult) and outcome.status == "ok":
        try:
            prepared = await asyncio.to_thread(store.prepare, outcome.body, job.calendar_tz)
        except FetchFailure as refused:
            failure = refused
        except Exception as exc:  # the class only
            logger.warning("events subscription parse failed (%s)", type(exc).__name__)
            failure = FetchFailure("internal")
    with tenant_scope(tenant):
        async with factory() as db:
            sub = await lease.fenced(db, sid, owner=owner, now=utc_now())
            if sub is None:
                await db.rollback()
                return Attempt("lease_lost")
            if sub.policy_generation != job.generation:
                # An edit changed the policy (public, internal access or the address) while this
                # fetch ran: its result came from the old one and is discarded (due again).
                await lease.release(db, sub)
                await finalize_session(db)
                return Attempt("lease_lost")
            stamp = utc_now()
            paused = sub.status == "paused"  # a pause made during the fetch outlives its result
            received = 0
            if prepared is not None:
                try:
                    async with db.begin_nested():
                        await store.store_feed(db, sub, prepared=prepared, now=stamp)
                    received = len(outcome.body)  # type: ignore[union-attr]
                except FetchFailure as refused:
                    failure = refused
                except Exception as exc:  # the class only; the savepoint left the items alone
                    logger.warning("events subscription store failed (%s)", type(exc).__name__)
                    failure = FetchFailure("internal")
            if failure is not None and failure.code == "try_later":
                # A server this tenant just contacted: not the feed's fault. Wait out the floor;
                # nothing is recorded against the subscription and nothing is shown.
                wait = failure.retry_after or constants.SUBSCRIPTION_HOST_FLOOR_SECONDS
                sub.next_fetch_at = stamp + timedelta(seconds=wait + rng.randint(0, 5))
                await lease.release(db, sub)
                await finalize_session(db)
                return Attempt("deferred")
            if failure is not None:
                _record_failure(sub, failure, job, stamp, rng)
            else:
                _record_success(sub, outcome, job, stamp, rng)  # type: ignore[arg-type]
            _charge_slowness(sub, stamp, seconds, failed=failure is not None)
            if paused:
                sub.status = "paused"
            await lease.release(db, sub)
            await finalize_session(db)
    if failure is not None:
        # The precise cause is for the operator; the address and its host never are.
        log = logger.warning if job.may_use_private and not job.public else logger.info
        log("events subscription %s failed: %s", sid, failure.code)
        return Attempt("failed", received)
    return Attempt("not_modified" if outcome.status == "not_modified" else "stored", received)  # type: ignore[union-attr]


async def attempt(
    factory: Any,
    tenant: str,
    sid: uuid.UUID,
    *,
    owner: str,
    now: datetime,
    settings: EventsSettings,
    fetcher: Callable[..., Any],
    rng: random.Random,
    utc_now: Callable[[], datetime],
    clock: Callable[[], float] = time.monotonic,
) -> Attempt:
    job = await _claim(factory, tenant, sid, owner, now, settings)
    if job is None:
        return Attempt("busy")
    started = clock()
    try:
        gate = TargetGate(factory, tenant, utc_now)  # the floor is on the server, per hop
        outcome = await _fetch(job, settings, fetcher, gate)
    except RuntimeError as exc:  # no secret key: an operator's problem, not the feed's
        logger.warning("events subscription not opened (%s)", type(exc).__name__)
        return Attempt("unavailable")
    seconds = clock() - started
    done = await _store(factory, tenant, sid, owner, job, outcome, rng, utc_now, seconds)
    return replace(done, seconds=seconds)
