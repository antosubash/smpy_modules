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
from dataclasses import dataclass
from datetime import datetime

from simple_module_db import finalize_session
from simple_module_db.listeners import TenantIsolationError, current_tenant_id
from sm_records.contracts.newsletter import (
    MAX_SUBSCRIBER_BATCH,
    iter_subscribers,
    subscription_lists,
)
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.audience import audience_filters
from sm_newsletter.campaigns.lifecycle import SCHEDULED, SENDING
from sm_newsletter.core.suppression import normalise_email, suppressed
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.core.upsert import insert_ignore
from sm_newsletter.models import Campaign, CampaignRender, Send
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


@dataclass(frozen=True)
class FreezeResult:
    started: bool
    queued: int
    suppressed: int


_LOST = FreezeResult(started=False, queued=0, suppressed=0)


async def start_due(factory: SessionFactory, *, now: datetime) -> int:
    """Freeze every due campaign; how many moved to ``sending``.

    A platform pass: with a tenant bound it raises ``TenantIsolationError``
    before reading anything. One campaign's failure is logged and the rest go on.
    """
    bound = current_tenant_id.get()
    if bound is not None:
        raise TenantIsolationError(f"cannot start every tenant's campaigns inside {bound!r}")
    started = 0
    for tenant, campaign_id in await due_campaigns(factory, now=now):
        try:
            result = await freeze(factory, tenant_id=tenant, campaign_id=campaign_id, now=now)
        except Exception:
            logger.exception(
                "newsletter: could not freeze campaign %s of tenant %s; the next tick retries",
                campaign_id,
                tenant,
            )
            continue
        started += int(result.started)
    return started


async def freeze(
    factory: SessionFactory, *, tenant_id: str, campaign_id: int, now: datetime
) -> FreezeResult:
    """Freeze one campaign's audience and start it (S18, under the fence)."""
    with tenant_scope(tenant_id):
        async with factory() as session:
            campaign = await _ready(session, tenant_id, campaign_id)
            claim = None
            if campaign is not None:
                claim = await claim_freeze(
                    session, tenant_id=tenant_id, campaign_id=campaign_id, now=now
                )
            await finalize_session(session)
        if campaign is None or claim is None:
            return _LOST
        list_key, audience = campaign
        async with factory() as session:
            lists = await subscription_lists(session, tenant_id=tenant_id)
            if list_key not in lists:
                await pause_unavailable(session, tenant_id, campaign_id, claim, now)
                await finalize_session(session)
                return _LOST
            await finalize_session(session)
        filters = audience_filters(audience)
        if not await _pages(factory, tenant_id, campaign_id, claim, list_key, filters, now):
            return _LOST
        return await _publish(factory, tenant_id, campaign_id, claim, now)


async def _ready(session: AsyncSession, tenant_id: str, campaign_id: int) -> tuple[str, str] | None:
    """``(list_type_key, audience)`` of a scheduled campaign with a render, else ``None``."""
    has_render = exists().where(
        CampaignRender.tenant_id == tenant_id, CampaignRender.campaign_id == Campaign.id
    )
    stmt = select(Campaign.list_type_key, Campaign.audience, has_render).where(
        Campaign.id == campaign_id, Campaign.tenant_id == tenant_id, Campaign.status == SCHEDULED
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    if not row[2]:
        logger.error(
            "newsletter: scheduled campaign %s of %s has no render", campaign_id, tenant_id
        )
        return None
    return row[0], row[1]


async def _pages(
    factory: SessionFactory,
    tenant_id: str,
    campaign_id: int,
    claim: FreezeClaim,
    list_key: str,
    filters: list[str],
    now: datetime,
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
            hits = [hit for hit in hits if hit.email.strip()]
            emails = [hit.email for hit in hits]
            blocked = await suppressed(session, tenant_id=tenant_id, emails=emails)
            if not await hold_freeze(
                session, claim, tenant_id=tenant_id, campaign_id=campaign_id, now=now
            ):
                await session.rollback()
                return False
            rows = [
                {
                    "tenant_id": tenant_id,
                    "campaign_id": campaign_id,
                    "record_uuid": hit.uuid,
                    "email": hit.email.strip(),
                    "first_name": hit.first_name,
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
    factory: SessionFactory, tenant_id: str, campaign_id: int, claim: FreezeClaim, now: datetime
) -> FreezeResult:
    """Count this generation's rows and move the campaign to ``sending``, if
    the claim still holds (renewed first, so the count and the move see the
    same rows)."""
    async with factory() as session:
        if not await hold_freeze(
            session, claim, tenant_id=tenant_id, campaign_id=campaign_id, now=now
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
