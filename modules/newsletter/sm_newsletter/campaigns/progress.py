"""A campaign's progress and the estimate of when a send would finish (rulings S16, S17).

The relay's quota is the deployment's, so the queue ahead of a campaign is
counted across tenants (:func:`queued_ahead`); like the budget count it
returns a number, never a row.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from simple_module_db import finalize_session
from simple_module_db.tenancy import all_tenants
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.access import Roles
from sm_newsletter.campaigns.audience import AUDIENCE_ALL, audience_count
from sm_newsletter.campaigns.lifecycle import SENDING, split_paused
from sm_newsletter.core import tenancy
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.models import Campaign, Send
from sm_newsletter.sending.budget import DAY, MINUTE
from sm_newsletter.sending.ledger import SessionFactory
from sm_newsletter.web.schemas.sending import EstimateOut, ProgressOut

__all__ = ["daily_rate", "estimate", "estimate_finish", "progress", "queued_ahead"]

_SEND = Send.__table__  # ty: ignore[unresolved-attribute]
_CAMPAIGN = Campaign.__table__  # ty: ignore[unresolved-attribute]
_DAY_SECONDS = DAY.total_seconds()
_MINUTES_PER_DAY = DAY // MINUTE


def daily_rate(settings: NewsletterSettings) -> int:
    """Messages per day the relay takes: the daily limit, or less if the minute limit is tighter."""
    return min(settings.daily_limit, settings.per_minute_limit * _MINUTES_PER_DAY)


def estimate_finish(*, start: datetime, ahead: int, own: int, rate: int) -> datetime:
    """``start`` plus ``(ahead + own)`` messages at ``rate`` per day."""
    try:
        return start + timedelta(seconds=_DAY_SECONDS * (ahead + own) / rate)
    except OverflowError:
        return datetime.max.replace(tzinfo=start.tzinfo)


async def queued_ahead(factory: SessionFactory, *, started_before: datetime | None) -> int:
    """``queued`` rows of ``sending`` campaigns, every tenant's, that started before
    ``started_before`` (``None``: any), which already leaves a campaign out of
    its own queue.
    A number only, under the framework's ``all_tenants()``."""
    stmt = (
        select(func.count())
        .select_from(_SEND.join(_CAMPAIGN, (_SEND.c.campaign_id == _CAMPAIGN.c.id)))
        .where(
            _SEND.c.tenant_id == _CAMPAIGN.c.tenant_id,
            _SEND.c.status == "queued",
            _CAMPAIGN.c.status == SENDING,
        )
    )
    if started_before is not None:
        stmt = stmt.where(_CAMPAIGN.c.started_at < started_before)
    with all_tenants():
        async with factory() as session:
            count = (await session.execute(tenancy.all_tenants(stmt))).scalar_one()
            await finalize_session(session)
    return int(count)


async def _counts(session: AsyncSession, tenant_id: str, campaign_id: int) -> dict[str, int]:
    stmt = (
        select(_SEND.c.status, func.count())
        .where(_SEND.c.tenant_id == tenant_id, _SEND.c.campaign_id == campaign_id)
        .group_by(_SEND.c.status)
    )
    return {str(status): int(n) for status, n in (await session.execute(stmt)).all()}


async def progress(
    session: AsyncSession,
    factory: SessionFactory,
    settings: NewsletterSettings,
    *,
    tenant_id: str,
    campaign: Campaign,
    now: datetime,
) -> ProgressOut:
    """The send rows counted by status, and for a ``sending`` campaign when it should end."""
    assert campaign.id is not None
    by = await _counts(session, tenant_id, campaign.id)
    rate = daily_rate(settings)
    finish = None
    if campaign.status == SENDING and campaign.started_at is not None:
        ahead = await queued_ahead(factory, started_before=campaign.started_at)
        own = by.get("queued", 0) + by.get("sending", 0)
        finish = estimate_finish(start=now, ahead=ahead, own=own, rate=rate)
    code, detail = split_paused(campaign.paused_reason)
    return ProgressOut(
        status=campaign.status,
        recipients=campaign.recipient_count,
        queued=by.get("queued", 0),
        sending=by.get("sending", 0),
        sent=by.get("sent", 0),
        failed=by.get("failed", 0),
        bounced=by.get("bounced", 0),
        suppressed=by.get("suppressed", 0),
        skipped=by.get("skipped_unsubscribed", 0),
        cancelled=by.get("cancelled", 0),
        paused_code=code,
        paused_detail=detail,
        scheduled_at=campaign.scheduled_at,
        started_at=campaign.started_at,
        finished_at=campaign.finished_at,
        estimated_finish=finish,
        daily_rate=rate,
    )


async def estimate(
    session: AsyncSession,
    factory: SessionFactory,
    settings: NewsletterSettings,
    *,
    tenant_id: str,
    campaign: Campaign,
    at: datetime,
    roles: Roles,
    reads_subscribers: bool = True,
) -> EstimateOut:
    """When a send starting at ``at`` would end. The recipient count is approximate:
    suppressions are not subtracted. A caller without ``records.view``
    (``reads_subscribers`` false) gets no count for a tag or segment audience,
    which would answer questions about subscriber fields, and a finish computed
    on the whole list: an upper bound."""
    hidden = not reads_subscribers and campaign.audience != AUDIENCE_ALL
    recipients = await audience_count(
        session,
        tenant_id=tenant_id,
        list_type_key=campaign.list_type_key,
        audience=AUDIENCE_ALL if hidden else campaign.audience,
        roles=roles,
    )
    ahead = await queued_ahead(factory, started_before=None)
    rate = daily_rate(settings)
    return EstimateOut(
        recipients=None if hidden else recipients,
        estimated_finish=estimate_finish(start=at, ahead=ahead, own=recipients, rate=rate),
        overlaps=ahead > 0,
        daily_rate=rate,
    )
