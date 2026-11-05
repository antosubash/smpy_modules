"""A campaign's status machine (ruling S14): schedule, unschedule, pause, resume, cancel.

Every transition is one conditional Core ``UPDATE``
(:mod:`~sm_newsletter.campaigns.transition`) pinned to the campaign's id, its
tenant and the statuses it may leave, bumping ``revision``. When it changes no
row, the campaign is read again to say why. The functions here never commit:
the caller does, so a refusal leaves nothing behind.

The freeze fence (amendment A1): ``schedule``, ``unschedule`` and a cancel from
``scheduled`` bump ``freeze_gen`` and release the freeze claim in the same
``UPDATE``, so a freezer still working on the old generation writes nothing
more. ``unschedule`` then deletes the campaign's send rows: its ``UPDATE`` came
first, so it waited for any freeze page in flight, and nothing of a campaign
that never started was sent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import case, delete, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns._refusal import DRAFT
from sm_newsletter.campaigns.access import Roles, check_list, require_campaign
from sm_newsletter.campaigns.audience import audience_filters
from sm_newsletter.campaigns.checks import (
    check_campaign_headers,
    check_https,
    check_no_capability_fields,
    check_scheduled_at,
    check_sender,
)
from sm_newsletter.campaigns.snapshot import build_render, drop_render, store_render
from sm_newsletter.campaigns.transition import apply_transition
from sm_newsletter.content.blocks import parse_body
from sm_newsletter.content.context import render_context
from sm_newsletter.core import constants
from sm_newsletter.core.errors import (
    EmptyCampaign,
    InvalidCampaign,
    InvalidTransition,
    NotADraft,
    StaleCampaign,
)
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.models import Campaign, Send

SCHEDULED, SENDING, PAUSED, CANCELLED = "scheduled", "sending", "paused", "cancelled"
MAX_PAUSED_REASON = 1000
# Bumped generation, released claim: an old freezer's next write matches nothing.
_FENCE: dict[str, Any] = {
    "freeze_gen": Campaign.freeze_gen + 1,
    "freeze_owner": None,
    "freeze_until": None,
}


def paused_reason(code: str, detail: str = "") -> str:
    """``"<code>|<detail>"``, clipped to the column (ruling S13)."""
    if code not in constants.PAUSE_CODES:
        raise ValueError(f"unknown pause code: {code}")
    return f"{code}|{detail}"[:MAX_PAUSED_REASON]


def split_paused(reason: str | None) -> tuple[str | None, str | None]:
    """``(code, detail)`` from a stored reason; an empty detail is ``None``."""
    if not reason:
        return None, None
    code, _, detail = reason.partition("|")
    return code, detail or None


async def schedule(
    app: Any,
    session: AsyncSession,
    *,
    tenant_id: str,
    campaign_id: int,
    roles: Roles,
    expected_revision: int,
    scheduled_at: datetime | None,
    now: datetime,
) -> Campaign:
    """``draft -> scheduled`` at ``scheduled_at`` (``None``: now), with the
    render snapshot, after ruling S19's checks in its order."""
    settings: NewsletterSettings = getattr(app.state, constants.PACKAGE).settings
    campaign = await require_campaign(
        session, tenant_id=tenant_id, campaign_id=campaign_id, roles=roles
    )
    if campaign.status != DRAFT:
        raise NotADraft()
    if campaign.revision != expected_revision:
        raise StaleCampaign()
    await check_list(session, tenant_id=tenant_id, type_key=campaign.list_type_key, roles=roles)
    audience_filters(campaign.audience)
    check_sender(settings)
    check_campaign_headers(campaign)
    if not campaign.subject.strip():
        raise InvalidCampaign("subject: required")
    if not parse_body(campaign.body):
        raise EmptyCampaign()
    ctx = await render_context(app, tenant_id=tenant_id)
    snap = build_render(settings, campaign, ctx, tenant_id=tenant_id, now=now)
    when = check_scheduled_at(scheduled_at, now)
    check_https(settings, ctx)
    check_no_capability_fields(campaign)
    values = {"status": SCHEDULED, "scheduled_at": when, "updated_at": now, **_FENCE}
    scheduled = await apply_transition(
        session, tenant_id, campaign_id, roles, (DRAFT,), values, revision=expected_revision
    )
    await store_render(session, snap)
    return scheduled


async def unschedule(
    session: AsyncSession, *, tenant_id: str, campaign_id: int, roles: Roles, expected_revision: int
) -> Campaign:
    """``scheduled -> draft``, or ``paused -> draft`` for a campaign never
    frozen (``started_at`` empty: paused at freeze, nothing sent); the
    snapshot and any send rows are deleted. A started campaign can only be
    cancelled: 409 ``invalid_transition``."""
    campaign = await require_campaign(
        session, tenant_id=tenant_id, campaign_id=campaign_id, roles=roles
    )
    if campaign.status == PAUSED and campaign.started_at is not None:
        raise InvalidTransition()
    values = {"status": DRAFT, "scheduled_at": None, "paused_reason": None, **_FENCE}
    never_started = or_(Campaign.status == SCHEDULED, Campaign.started_at.is_(None))
    draft = await apply_transition(
        session,
        tenant_id,
        campaign_id,
        roles,
        (SCHEDULED, PAUSED),
        values,
        revision=expected_revision,
        where=[never_started],
    )
    await drop_render(session, tenant_id=tenant_id, campaign_id=campaign_id)
    await session.execute(
        delete(Send)
        .where(Send.tenant_id == tenant_id, Send.campaign_id == campaign_id)
        .execution_options(synchronize_session=False)
    )
    return draft


async def pause(
    session: AsyncSession, *, tenant_id: str, campaign_id: int, roles: Roles, now: datetime
) -> Campaign:
    """``sending -> paused``, reason ``manual``."""
    await require_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id, roles=roles)
    reason = paused_reason(constants.PAUSE_MANUAL)
    values = {"status": PAUSED, "paused_reason": reason, "updated_at": now}
    return await apply_transition(session, tenant_id, campaign_id, roles, (SENDING,), values)


async def resume(
    session: AsyncSession, *, tenant_id: str, campaign_id: int, roles: Roles, now: datetime
) -> Campaign:
    """``paused -> sending`` once frozen, else back to ``scheduled`` for now."""
    campaign = await require_campaign(
        session, tenant_id=tenant_id, campaign_id=campaign_id, roles=roles
    )
    values: dict[str, Any] = {"status": SENDING, "paused_reason": None, "updated_at": now}
    if campaign.started_at is None:
        values |= {"status": SCHEDULED, "scheduled_at": now}
    # Pinned to the revision read, so the target matches ``started_at`` as read;
    # a race answers ``invalid_transition``, not ``stale``.
    return await apply_transition(
        session,
        tenant_id,
        campaign_id,
        roles,
        (PAUSED,),
        values,
        revision=campaign.revision,
        stale_on_revision=False,
    )


async def cancel(
    session: AsyncSession, *, tenant_id: str, campaign_id: int, roles: Roles, now: datetime
) -> Campaign:
    """``scheduled``/``sending``/``paused -> cancelled``; the ``queued`` rows too."""
    await require_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id, roles=roles)
    from_scheduled = Campaign.status == SCHEDULED
    values = {
        "status": CANCELLED,
        "finished_at": now,
        "updated_at": now,
        # The fence only for a campaign a freezer may still be working on.
        "freeze_gen": case((from_scheduled, Campaign.freeze_gen + 1), else_=Campaign.freeze_gen),
        "freeze_owner": None,
        "freeze_until": None,
    }
    from_statuses = (SCHEDULED, SENDING, PAUSED)
    cancelled = await apply_transition(
        session, tenant_id, campaign_id, roles, from_statuses, values
    )
    await session.execute(
        update(Send)
        .where(
            Send.tenant_id == tenant_id,
            Send.campaign_id == campaign_id,
            Send.status == "queued",
        )
        .values(status=CANCELLED)
        .execution_options(synchronize_session=False)
    )
    return cancelled
