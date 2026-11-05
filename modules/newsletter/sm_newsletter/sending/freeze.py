"""Freeze: a due campaign's audience becomes its send rows (ruling S18).

**The fence** (amendments A1, A2; :mod:`.freeze_fence`). A freeze has one
owner per campaign, for one generation, taken by :func:`claim_freeze`. Every
page renews it with :func:`hold_freeze` *first* inside the page's
transaction, so a page's rows commit only while the claim holds, and a
concurrent ``unschedule``/``cancel`` (which bumps the generation and releases
the claim, ``campaigns.lifecycle``) serialises against it. The final
``scheduled -> sending`` is conditional on the claim too. A freezer that lost
its claim writes nothing more: the path that took it cleaned up the rows.

**Idempotent.** Rows are inserted ignoring ``(tenant_id, campaign_id,
record_uuid)`` and stamped with the generation; the counts come from the rows
of that generation. A crashed freezer's rows stay, and after
:data:`FREEZE_LEASE` the next tick claims the campaign again and goes on.

**Tenancy.** :func:`due_campaigns` is a deliberate cross-tenant read returning
``(tenant_id, id)`` pairs. :func:`start_due` runs with no tenant bound and
freezes each campaign under its own tenant, each step in a fresh session.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from simple_module_db import finalize_session
from simple_module_db.listeners import TenantIsolationError, current_tenant_id
from sm_records.contracts.newsletter import (
    MAX_SUBSCRIBER_BATCH,
    iter_subscribers,
    subscription_lists,
)
from sqlalchemy import func, select

from sm_newsletter.campaigns.checks import bases_https
from sm_newsletter.campaigns.lifecycle import SENDING
from sm_newsletter.core import constants
from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.constants import MAX_EMAIL_LEN, MAX_FIRST_NAME_LEN
from sm_newsletter.core.suppression import normalise_email, suppressed
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.core.upsert import insert_ignore
from sm_newsletter.models import Campaign, Send
from sm_newsletter.sending.freeze_fence import (
    FREEZE_LEASE,
    FreezeClaim,
    SessionFactory,
    claim_freeze,
    due_campaigns,
    held,
    hold_freeze,
    pause_unavailable,
    update_campaign,
)

__all__ = [
    "FREEZE_LEASE",
    "PAGE",
    "FreezeClaim",
    "FreezeResult",
    "claim_freeze",
    "due_campaigns",
    "freeze",
    "hold_freeze",
    "start_due",
]

logger = logging.getLogger(__name__)

PAGE = MAX_SUBSCRIBER_BATCH
QUEUED, SUPPRESSED = "queued", "suppressed"

_SEND = Send.__table__  # ty: ignore[unresolved-attribute]

Clock = Callable[[], datetime]
"""The wall clock the fence reads: every claim and renewal asks it afresh, so a
long freeze keeps its lease. ``now`` stays the tick's (the due cutoff and
``started_at``)."""


@dataclass(frozen=True)
class FreezeResult:
    started: bool
    queued: int
    suppressed: int


_LOST = FreezeResult(started=False, queued=0, suppressed=0)


async def start_due(
    factory: SessionFactory, *, now: datetime, clock: Clock = utcnow, require_https: bool = False
) -> int:
    """Freeze every due campaign; how many moved to ``sending``. With
    ``require_https`` (the ``smtp`` transport) an insecure snapshot pauses instead.

    A platform pass: with a tenant bound it raises ``TenantIsolationError``
    before reading anything. One campaign's failure is logged and the rest go on.
    """
    bound = current_tenant_id.get()
    if bound is not None:
        raise TenantIsolationError(f"cannot start every tenant's campaigns inside {bound!r}")
    started = 0
    for tenant, campaign_id in await due_campaigns(factory, now=now):
        try:
            result = await freeze(
                factory,
                tenant_id=tenant,
                campaign_id=campaign_id,
                now=now,
                clock=clock,
                require_https=require_https,
            )
        except Exception as exc:
            # The class only: a database error's text (and traceback) carries
            # the page's SQL parameters, i.e. addresses and names.
            logger.error(
                "newsletter: could not freeze campaign %s of tenant %s (%s); the next tick retries",
                campaign_id,
                tenant,
                type(exc).__name__,
            )
            continue
        started += int(result.started)
    return started


async def freeze(
    factory: SessionFactory,
    *,
    tenant_id: str,
    campaign_id: int,
    now: datetime,
    clock: Clock = utcnow,
    require_https: bool = False,
) -> FreezeResult:
    """Freeze one campaign's audience and start it (S18, under the fence):
    ``now`` is the due cutoff the claim re-checks and ``started_at``; the
    lease is reckoned from ``clock()``. With ``require_https`` a snapshot
    whose bases are not both ``https://`` pauses the campaign from
    ``scheduled`` (``https_required``, nothing frozen) under the claim."""
    with tenant_scope(tenant_id):
        async with factory() as session:
            claim = await claim_freeze(
                session, tenant_id=tenant_id, campaign_id=campaign_id, now=clock(), due_by=now
            )
            insecure = claim is not None and require_https
            insecure = insecure and not bases_https(claim.content_base, claim.public_base)
            if insecure:
                logger.warning("newsletter: campaign %s of %s needs https", campaign_id, tenant_id)
                await pause_unavailable(
                    session, tenant_id, campaign_id, claim, now, constants.PAUSE_HTTPS_REQUIRED
                )
            await finalize_session(session)
        if claim is None or insecure:
            return _LOST
        # Only what the claim read: its list and audience belong to its generation.
        list_key, filters = claim.list_type_key, claim.audience_filters
        async with factory() as session:
            lists = await subscription_lists(session, tenant_id=tenant_id)
            if list_key not in lists:
                await pause_unavailable(session, tenant_id, campaign_id, claim, now)
                await finalize_session(session)
                return _LOST
            await finalize_session(session)
        if not await _pages(factory, tenant_id, campaign_id, claim, list_key, filters, clock):
            return _LOST
        return await _publish(factory, tenant_id, campaign_id, claim, now, clock)


async def _pages(
    factory: SessionFactory,
    tenant_id: str,
    campaign_id: int,
    claim: FreezeClaim,
    list_key: str,
    filters: list[str],
    clock: Clock,
) -> bool:
    """Every page of the audience into send rows; ``False`` once the claim is lost."""
    cursor: int | None = 0
    while cursor is not None:
        async with factory() as session:
            hits, cursor = await iter_subscribers(
                session,
                tenant_id=tenant_id,
                type_key=list_key,
                filters=filters,
                limit=PAGE,
                after=cursor,
            )
            # Records caps neither length; the send columns do. A blank or
            # over-long address could not be delivered and is left out; a long
            # name is clipped (Postgres would refuse the whole page).
            hits = [hit for hit in hits if 0 < len(hit.email.strip()) <= MAX_EMAIL_LEN]
            emails = [hit.email for hit in hits]
            blocked = await suppressed(session, tenant_id=tenant_id, emails=emails)
            if not await hold_freeze(
                session, claim, tenant_id=tenant_id, campaign_id=campaign_id, now=clock()
            ):
                await session.rollback()
                return False
            rows = [
                {
                    "tenant_id": tenant_id,
                    "campaign_id": campaign_id,
                    "record_uuid": hit.uuid,
                    "email": hit.email.strip(),
                    "first_name": (hit.first_name or "")[:MAX_FIRST_NAME_LEN] or None,
                    "status": SUPPRESSED if normalise_email(hit.email) in blocked else QUEUED,
                    "freeze_gen": claim.gen,
                }
                for hit in hits
            ]
            if rows:
                await insert_ignore(
                    session, _SEND, rows, conflict=["tenant_id", "campaign_id", "record_uuid"]
                )
            await finalize_session(session)
    return True


async def _publish(
    factory: SessionFactory,
    tenant_id: str,
    campaign_id: int,
    claim: FreezeClaim,
    now: datetime,
    clock: Clock,
) -> FreezeResult:
    """Count this generation's rows and move the campaign to ``sending``, if
    the claim still holds (renewed first, so the count and the move see the
    same rows)."""
    async with factory() as session:
        if not await hold_freeze(
            session, claim, tenant_id=tenant_id, campaign_id=campaign_id, now=clock()
        ):
            await session.rollback()
            return _LOST
        stmt = (
            select(_SEND.c.status, func.count())
            .where(
                _SEND.c.tenant_id == tenant_id,
                _SEND.c.campaign_id == campaign_id,
                _SEND.c.freeze_gen == claim.gen,
                _SEND.c.status.in_((QUEUED, SUPPRESSED)),
            )
            .group_by(_SEND.c.status)
        )
        counts = Counter({status: int(n) for status, n in (await session.execute(stmt)).all()})
        values = {
            "status": SENDING,
            "started_at": now,
            "recipient_count": counts[QUEUED],
            "suppressed_count": counts[SUPPRESSED],
            "freeze_owner": None,
            "freeze_until": None,
            "revision": Campaign.revision + 1,
            "updated_at": now,
        }
        if not await update_campaign(session, held(tenant_id, campaign_id, claim), values):
            await session.rollback()
            return _LOST
        await finalize_session(session)
    return FreezeResult(started=True, queued=counts[QUEUED], suppressed=counts[SUPPRESSED])
