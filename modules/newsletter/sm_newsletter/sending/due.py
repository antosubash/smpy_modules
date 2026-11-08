"""The next due row of a ``sending`` campaign, with what compose needs."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.lifecycle import SENDING
from sm_newsletter.models import Campaign, CampaignRender, Link, Send
from sm_newsletter.sending import rows

__all__ = ["next_due"]

logger = logging.getLogger(__name__)


async def next_due(
    session: AsyncSession,
    tenant_id: str,
    campaign_id: int,
    now: datetime,
    *,
    read_links: bool = True,
) -> tuple[Send, str, CampaignRender, dict[int, str]] | None:
    """The next due row, the campaign's list, its render and its tracked links
    (position to URL), detached from the session (so the reads can end), or ``None``.
    With clicks tracked ``fill`` builds the click URL and reads no stored link, so
    the caller passes ``read_links=False`` and the dict is empty."""
    stmt = select(Campaign.status, Campaign.list_type_key).where(
        Campaign.id == campaign_id, Campaign.tenant_id == tenant_id
    )
    campaign = (await session.execute(stmt)).first()
    if campaign is None or campaign[0] != SENDING:
        return None
    row = await rows.next_row(session, tenant_id=tenant_id, campaign_id=campaign_id, now=now)
    if row is None:
        return None
    render_stmt = select(CampaignRender).where(
        CampaignRender.tenant_id == tenant_id, CampaignRender.campaign_id == campaign_id
    )
    render = (await session.execute(render_stmt)).scalars().first()
    if render is None:
        logger.error("newsletter: sending campaign %s has no render", campaign_id)
        return None
    links: dict[int, str] = {}
    if read_links:
        link_stmt = select(Link.position, Link.url).where(
            Link.tenant_id == tenant_id, Link.campaign_id == campaign_id
        )
        links = {r.position: r.url for r in (await session.execute(link_stmt)).all()}
    session.expunge(row)
    session.expunge(render)
    return row, campaign[1], render, links
