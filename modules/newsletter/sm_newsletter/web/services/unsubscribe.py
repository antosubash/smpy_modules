"""What a POST to an unsubscribe link does (S8, S9).

**Order.** The MAC is verified before any statement runs, a request whose host
resolved another tenant is treated as forged, and only then is the token's
tenant bound and a session opened. Nothing here raises for a bad token: the
caller answers the same page whatever this returns.

**Records is the truth.** The opt-out is records' ``unsubscribe`` with the
cutoff ``send.sent_at`` (else the campaign's start): a person who signed up and
confirmed again after the mail keeps the subscription, and nothing is written.

**The suppression** (``unsubscribed``, the campaign's list,
``unsubscribe_page``) goes in the same transaction when records wrote, and also
when the subscriber is gone, trashed or already unsubscribed, or the type is no
longer a list: the mail went to that address, and its owner asked to stop.
Never for a ``pending`` subscriber or one confirmed after the cutoff.
``unsubscribe_count`` counts only records' writes, so a repeat click does not.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from simple_module_db import finalize_session
from sm_records.contracts.newsletter import (
    SubscriberFilterError,
    subscribers_by_uuid,
    unsubscribe,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import constants, tokens
from sm_newsletter.core.suppression import suppress
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Campaign, Send
from sm_newsletter.sending.rows import bump

__all__ = ["unsubscribe_by_token"]

logger = logging.getLogger(__name__)

_SEND = Send.__table__  # ty: ignore[unresolved-attribute]
_CAMPAIGN = Campaign.__table__  # ty: ignore[unresolved-attribute]
_GONE = frozenset({"unsubscribed"})
_warned_no_secret = False


def _secret(app: Any) -> str:
    global _warned_no_secret
    secret = tokens.host_secret(app)
    if not secret and not _warned_no_secret:
        _warned_no_secret = True
        logger.error("newsletter: no host secret_key; every unsubscribe link is refused")
    return secret


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def unsubscribe_by_token(
    app: Any, token: str, *, resolved_tenant: str | None, now: datetime
) -> bool:
    """``True`` only when records wrote. An invalid or foreign token is ``False``
    with no statement run."""
    secret = _secret(app)
    if not secret:
        return False
    claims = tokens.parse(secret, token)
    if claims is None:
        return False
    if resolved_tenant is not None and resolved_tenant != claims.tenant_id:
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
    cutoff = _aware(send.sent_at or campaign.started_at or now)
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


async def _gone(session: AsyncSession, tenant: str, list_key: str, uuid: str) -> bool:
    """Whether the subscriber is missing, trashed or already unsubscribed."""
    hit = (
        await subscribers_by_uuid(session, tenant_id=tenant, type_key=list_key, uuids=[uuid])
    ).get(uuid)
    return hit is None or hit.trashed or hit.status in _GONE
