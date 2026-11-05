"""A campaign's report: its counters, per-link clicks and a timeline (T14, B5, B6).

The counters come off the campaign row (every send); the rate numerators
``*_accepted`` are counted from the rows whose status is ``sent``, so a rate
over ``sent_count`` never passes 100 % (B5). Every statement pins ``tenant_id``.
Returns dataclasses only: the web layer maps them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.models import Campaign, Click, Link, Send
from sm_newsletter.tracking.timeline import Bucket, Point, bucketize

__all__ = ["LinkStat", "Report", "accepted_engagement", "campaign_report", "link_stats"]

_SENT = "sent"
_SKIPPED = "skipped_unsubscribed"


@dataclass(frozen=True)
class LinkStat:
    position: int
    url: str
    unique: int
    total: int


@dataclass(frozen=True)
class Report:
    campaign_id: int
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    recipients: int
    sent: int
    failed: int
    bounced: int
    suppressed: int
    skipped: int
    unsubscribed: int
    opens_unique: int
    opens_total: int
    clicks_unique: int
    clicks_total: int
    opens_unique_accepted: int
    clicks_unique_accepted: int
    tracking_opens: bool
    tracking_clicks: bool
    links: list[LinkStat]
    bucket: Bucket
    timeline: list[Point]


async def link_stats(session: AsyncSession, *, tenant_id: str, campaign_id: int) -> list[LinkStat]:
    """Every tracked link, clicked or not: unique desc, total desc, position asc."""
    unique = func.count(Click.id)
    total = func.coalesce(func.sum(Click.click_count), 0)
    stmt = (
        select(Link.position, Link.url, unique, total)
        .select_from(Link)
        .outerjoin(Click, (Click.link_id == Link.id) & (Click.tenant_id == tenant_id))
        .where(Link.tenant_id == tenant_id, Link.campaign_id == campaign_id)
        .group_by(Link.id, Link.position, Link.url)
        .order_by(unique.desc(), total.desc(), Link.position)
    )
    return [
        LinkStat(int(r[0]), str(r[1]), int(r[2]), int(r[3])) for r in await session.execute(stmt)
    ]


async def accepted_engagement(
    session: AsyncSession, *, tenant_id: str, campaign_ids: Sequence[int]
) -> dict[int, tuple[int, int]]:
    """``{campaign id: (opens, clicks)}`` over sends whose status is ``sent`` (B5)."""
    found = dict.fromkeys(campaign_ids, (0, 0))
    if not found:
        return found
    opened = func.sum(case((Send.opened_at.is_not(None), 1), else_=0))
    clicked = func.sum(case((Send.first_clicked_at.is_not(None), 1), else_=0))
    stmt = (
        select(Send.campaign_id, opened, clicked)
        .where(
            Send.tenant_id == tenant_id,
            Send.campaign_id.in_(list(found)),  # ty: ignore[unresolved-attribute]
            Send.status == _SENT,
        )
        .group_by(Send.campaign_id)
    )
    for cid, opens, clicks in await session.execute(stmt):
        found[int(cid)] = (int(opens or 0), int(clicks or 0))
    return found


async def _skipped(session: AsyncSession, tenant_id: str, campaign_id: int) -> int:
    stmt = select(func.count()).where(
        Send.tenant_id == tenant_id, Send.campaign_id == campaign_id, Send.status == _SKIPPED
    )
    return int(await session.scalar(stmt) or 0)


async def _timeline(
    session: AsyncSession, tenant_id: str, campaign: Campaign, now: datetime
) -> tuple[Bucket, list[Point]]:
    if campaign.started_at is None:
        return "hour", []
    stmt = select(Send.opened_at, Send.first_clicked_at).where(
        Send.tenant_id == tenant_id,
        Send.campaign_id == campaign.id,
        (Send.opened_at.is_not(None)) | (Send.first_clicked_at.is_not(None)),
    )
    rows = (await session.execute(stmt)).all()
    return bucketize(
        [r[0] for r in rows if r[0] is not None],
        [r[1] for r in rows if r[1] is not None],
        start=campaign.started_at,
        now=now,
    )


async def campaign_report(
    session: AsyncSession,
    settings: NewsletterSettings,
    *,
    tenant_id: str,
    campaign: Campaign,
    now: datetime,
) -> Report:
    assert campaign.id is not None
    cid = campaign.id
    accepted = await accepted_engagement(session, tenant_id=tenant_id, campaign_ids=[cid])
    bucket, timeline = await _timeline(session, tenant_id, campaign, now)
    return Report(
        campaign_id=cid,
        status=campaign.status,
        started_at=campaign.started_at,
        finished_at=campaign.finished_at,
        recipients=campaign.recipient_count,
        sent=campaign.sent_count,
        failed=campaign.failed_count,
        bounced=campaign.bounced_count,
        suppressed=campaign.suppressed_count,
        skipped=await _skipped(session, tenant_id, cid),
        unsubscribed=campaign.unsubscribe_count,
        opens_unique=campaign.open_unique_count,
        opens_total=campaign.open_total_count,
        clicks_unique=campaign.click_unique_count,
        clicks_total=campaign.click_total_count,
        opens_unique_accepted=accepted[cid][0],
        clicks_unique_accepted=accepted[cid][1],
        tracking_opens=settings.tracking_opens,
        tracking_clicks=settings.tracking_clicks,
        links=await link_stats(session, tenant_id=tenant_id, campaign_id=cid),
        bucket=bucket,
        timeline=timeline,
    )
