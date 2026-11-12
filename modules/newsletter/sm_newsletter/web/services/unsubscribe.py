"""What a POST to an unsubscribe link does (S8, S9).

**Order.** The MAC is verified before any statement runs, a request whose host
resolved another tenant (``resolved_tenant``: the endpoint passes only a
host-derived one) is treated as forged, and only then is the token's
tenant bound and a session opened. Nothing here raises for a bad token: the
caller answers the same page whatever this returns.

**Records is the truth.** The opt-out is records' ``unsubscribe`` with the
cutoff of when this message went out (:func:`_cutoff`): a person who signed up
and confirmed again after the mail keeps the subscription, and nothing is
written.

**The suppression** (``unsubscribed``, the campaign's list,
``unsubscribe_page``) goes in the same transaction when records wrote, and also
when the subscriber is gone, trashed or already unsubscribed, or the type is no
longer a list: the mail went to that address, and its owner asked to stop.
Never for a ``pending`` subscriber or one confirmed after the cutoff.
``unsubscribe_count`` counts only records' writes, so a repeat click does not.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from simple_module_core.datetimes import aware
from simple_module_db import finalize_session
from sm_records.contracts.newsletter import (
    SubscriberFilterError,
    subscribers_by_uuid,
    unsubscribe,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import constants, tokens
from sm_newsletter.core.suppression import suppress
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Campaign, Send, SendAttempt
from sm_newsletter.sending.rows import bump

__all__ = ["unsubscribe_by_token"]

logger = logging.getLogger(__name__)

# SQLModel types a table class without `__table__`, which SQLAlchemy sets on it.
_SEND = Send.__table__  # ty: ignore[unresolved-attribute]  # pyright: ignore[reportAttributeAccessIssue]
_CAMPAIGN = Campaign.__table__  # ty: ignore[unresolved-attribute]  # pyright: ignore[reportAttributeAccessIssue]
_ATTEMPT = SendAttempt.__table__  # ty: ignore[unresolved-attribute]  # pyright: ignore[reportAttributeAccessIssue]


async def unsubscribe_by_token(
    app: Any, token: str, *, resolved_tenant: str | None, now: datetime
) -> bool:
    """``True`` only when records wrote. An invalid or foreign token is ``False``
    with no statement run."""
    claims = tokens.verify(
        app,
        token,
        purpose="u",
        resolved_tenant=resolved_tenant,
        refused="every unsubscribe link is refused",
    )
    if claims is None:
        return False
    with tenant_scope(claims.tenant_id):
        async with app.state.sm.db.session_factory() as session:
            wrote = await _apply(app, session, claims, now)
            await finalize_session(session)
            return wrote


async def _apply(app: Any, session: AsyncSession, claims: tokens.SendToken, now: datetime) -> bool:
    tenant = claims.tenant_id
    send = (
        await session.execute(
            select(_SEND.c.record_uuid, _SEND.c.email, _SEND.c.sent_at).where(
                _SEND.c.id == claims.send_id,
                _SEND.c.tenant_id == tenant,
                _SEND.c.campaign_id == claims.campaign_id,
            )
        )
    ).one_or_none()
    campaign = (
        await session.execute(
            select(_CAMPAIGN.c.list_type_key, _CAMPAIGN.c.started_at).where(
                _CAMPAIGN.c.id == claims.campaign_id, _CAMPAIGN.c.tenant_id == tenant
            )
        )
    ).one_or_none()
    if send is None or campaign is None:
        return False
    cutoff = await _cutoff(session, tenant, claims.send_id, send.sent_at, campaign.started_at, now)
    list_key = campaign.list_type_key
    try:
        wrote = await unsubscribe(
            session,
            tenant_id=tenant,
            type_key=list_key,
            uuid=send.record_uuid,
            unless_confirmed_after=cutoff,
            settings=app.state.sm_records.settings,
            bus=app.state.sm.event_bus,
        )
        gone = wrote or await _gone(session, tenant, list_key, send.record_uuid)
    except SubscriberFilterError:  # the type stopped being a list
        wrote, gone = False, True
    if gone:
        await suppress(
            session,
            tenant_id=tenant,
            email=send.email,
            reason=constants.REASON_UNSUBSCRIBED,
            source=constants.SOURCE_UNSUBSCRIBE_PAGE,
            list_type_key=list_key,
            now=now,
        )
    if wrote:
        await bump(session, tenant_id=tenant, campaign_id=claims.campaign_id, unsubscribe_count=1)
        logger.info("newsletter: send %s unsubscribed", claims.send_id)
    return wrote


async def _cutoff(
    session: AsyncSession,
    tenant: str,
    send_id: int,
    sent_at: datetime | None,
    started_at: datetime | None,
    now: datetime,
) -> datetime:
    """When this message went out: ``sent_at``; for an unknown outcome (no
    ``sent_at``) the latest attempt opened for this send, since a campaign can
    run for days after its ``started_at``; else the start, else ``now``."""
    if sent_at is not None:
        return aware(sent_at)
    stmt = select(func.max(_ATTEMPT.c.attempted_at)).where(
        _ATTEMPT.c.tenant_id == tenant, _ATTEMPT.c.send_id == send_id
    )
    attempted = (await session.execute(stmt)).scalar_one_or_none()
    return aware(attempted or started_at or now)


async def _gone(session: AsyncSession, tenant: str, list_key: str, uuid: str) -> bool:
    """Whether the subscriber is missing, trashed or already unsubscribed."""
    hit = (
        await subscribers_by_uuid(session, tenant_id=tenant, type_key=list_key, uuids=[uuid])
    ).get(uuid)
    return hit is None or hit.trashed or hit.status == "unsubscribed"
