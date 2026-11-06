"""The render snapshot: a campaign's email, rendered once when it is scheduled (ruling S1).

The worker never builds the app, so branding, the sender and the bases are
resolved here, in the request, and stored in ``newsletter_campaign_render``
with the merge tags left in place; the dispatcher only personalises it. It is
the test send's message (:mod:`~sm_newsletter.campaigns.test_send`) without the
``[TEST]`` prefix and without a recipient's values. Unscheduling drops it, so
scheduling again renders afresh.
"""

from __future__ import annotations

from datetime import datetime
from email.utils import formataddr
from typing import Any

from simple_module_db import mark_written
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.content.blocks import parse_body
from sm_newsletter.content.context import render_context
from sm_newsletter.content.render import WARN_RELATIVE, RenderContext, RenderInput, render
from sm_newsletter.core import constants
from sm_newsletter.core.errors import InvalidCampaign, PublicBaseUrlRequired
from sm_newsletter.core.headers import check_header_text
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.models import Campaign, CampaignRender


def build_render(
    settings: NewsletterSettings,
    campaign: Campaign,
    ctx: RenderContext,
    *,
    tenant_id: str,
    now: datetime,
) -> CampaignRender:
    """The snapshot row, not yet stored. 422 ``public_base_url_required`` when
    the links would be relative; 422 ``invalid_campaign`` when a header value
    as stored (sender, subject, reply-to) would carry a line break."""
    template = render(
        RenderInput(campaign.subject, campaign.preheader, parse_body(campaign.body)), ctx
    )
    if WARN_RELATIVE in template.warnings:
        raise PublicBaseUrlRequired()
    row = CampaignRender(
        tenant_id=tenant_id,
        campaign_id=campaign.id,
        subject=template.subject,
        html=template.html,
        text=template.text,
        sender=formataddr(
            (campaign.from_name or settings.from_name, settings.from_address.strip())
        ),
        reply_to=campaign.reply_to or settings.reply_to or None,
        public_base=ctx.public_base,
        content_base=ctx.content_base,
        locale=ctx.locale,
        rendered_at=now,
    )
    for field in ("sender", "subject", "reply_to"):  # the exact values stored (amendment 5)
        value = getattr(row, field)
        try:
            check_header_text(value or "", field=field)
        except ValueError as exc:
            raise InvalidCampaign(str(exc)) from None
    return row


async def store_render(session: AsyncSession, row: CampaignRender) -> CampaignRender:
    """Write ``row``, replacing the campaign's previous snapshot if any."""
    assert row.campaign_id is not None
    await drop_render(session, tenant_id=row.tenant_id, campaign_id=row.campaign_id)
    session.add(row)
    await session.flush()
    return row


async def snapshot_render(
    app: Any, session: AsyncSession, *, tenant_id: str, campaign: Campaign, now: datetime
) -> CampaignRender:
    """Render ``campaign`` for ``tenant_id`` and store it; the caller commits."""
    settings: NewsletterSettings = getattr(app.state, constants.PACKAGE).settings
    ctx = await render_context(app, tenant_id=tenant_id)
    row = build_render(settings, campaign, ctx, tenant_id=tenant_id, now=now)
    return await store_render(session, row)


async def drop_render(session: AsyncSession, *, tenant_id: str, campaign_id: int) -> None:
    """Delete the campaign's snapshot, if any; the caller commits."""
    stmt = delete(CampaignRender).where(
        CampaignRender.tenant_id == tenant_id, CampaignRender.campaign_id == campaign_id
    )
    await session.execute(stmt)
    mark_written(session)
