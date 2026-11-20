"""One subscription's pass, the same for the beat and for "refresh now".

*Claim* (compare and set, committed before anything is fetched), open the address, *fetch with no
session open*, then, in one transaction fenced on the lease, store the feed or record the failure,
release the lease and commit. A fetch that outlives its lease cannot store; a crashed one leaves a
lease that simply expires. A failure is one code from a closed set, recorded with the backoff of
:mod:`~sm_events.feeds.subscriptions.schedule`; the old items stay. Only counts and the
subscription's id reach the log, never the address.
"""

from __future__ import annotations

import logging
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from simple_module_db import finalize_session
from sqlalchemy import select

from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.importing.staging import effective_max_bytes
from sm_events.feeds.subscriptions import lease, schedule, urls
from sm_events.feeds.subscriptions.errors import FetchFailure
from sm_events.feeds.subscriptions.fetch import FetchResult
from sm_events.feeds.subscriptions.policy import effective
from sm_events.feeds.subscriptions.store import store_feed
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


@dataclass(frozen=True)
class Attempt:
    outcome: str
    """``stored``, ``not_modified``, ``failed``, ``lease_lost``, ``busy`` or ``unavailable``."""
    received: int = 0


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
    job: _Job, settings: EventsSettings, fetcher: Callable[..., Any]
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
        )
    except FetchFailure as failure:
        return failure
    except Exception as exc:  # the class only: its message can quote the address
        logger.warning("events subscription fetch failed unexpectedly (%s)", type(exc).__name__)
        return FetchFailure("internal")
    finally:
        del url


def _record_failure(
    sub: Subscription, failure: FetchFailure, job: _Job, stamp: datetime, rng: random.Random
) -> None:
    failures = sub.consecutive_failures + 1
    at, status = schedule.after_failure(
        stamp, job.minutes, failures, failure.code, rng, retry_after=failure.retry_after
    )
    sub.status, sub.error_code, sub.last_http_status = status, failure.code, failure.http_status
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
) -> Attempt:
    """Store the result (or record the failure) in one transaction fenced on the lease."""
    with tenant_scope(tenant):
        async with factory() as db:
            sub = await lease.fenced(db, sid, owner=owner, now=utc_now())
            if sub is None:
                await db.rollback()
                return Attempt("lease_lost")
            stamp = utc_now()
            paused = sub.status == "paused"  # a pause made during the fetch outlives its result
            failure = outcome if isinstance(outcome, FetchFailure) else None
            received = 0
            if isinstance(outcome, FetchResult) and outcome.status == "ok":
                try:
                    async with db.begin_nested():
                        await store_feed(
                            db, sub, calendar_tz=job.calendar_tz, body=outcome.body, now=stamp
                        )
                    received = len(outcome.body)
                except FetchFailure as refused:
                    failure = refused
                except Exception as exc:  # the class only; the savepoint left the items alone
                    logger.warning("events subscription store failed (%s)", type(exc).__name__)
                    failure = FetchFailure("internal")
            if failure is not None:
                _record_failure(sub, failure, job, stamp, rng)
            else:
                _record_success(sub, outcome, job, stamp, rng)  # type: ignore[arg-type]
            if paused:
                sub.status = "paused"
            await lease.release(db, sub)
            await finalize_session(db)
    if failure is not None:
        logger.info("events subscription %s failed: %s", sid, failure.code)
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
) -> Attempt:
    job = await _claim(factory, tenant, sid, owner, now, settings)
    if job is None:
        return Attempt("busy")
    try:
        outcome = await _fetch(job, settings, fetcher)
    except RuntimeError as exc:  # no secret key: an operator's problem, not the feed's
        logger.warning("events subscription not opened (%s)", type(exc).__name__)
        return Attempt("unavailable")
    return await _store(factory, tenant, sid, owner, job, outcome, rng, utc_now)
