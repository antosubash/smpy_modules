"""Deliver one recipient of a ``sending`` campaign (rulings S4, S6, S7; A3, A4).

The caller holds the dispatch lock. Per recipient, in this order:

1. read the campaign (a shortcut: the claim decides) and its next due row;
2. re-check the subscriber (still confirmed in records, not suppressed): an
   ineligible row is skipped with no SMTP call and no ledger row;
3. compose from the render snapshot (a bad header fails the row, unsent);
4. ``lock.renew()``;
5. the reservation, one transaction: ``lock.fence``, the conditional claim
   (the row still ``queued``, the campaign still ``sending``) and the
   ``pending`` attempt, committed together before the SMTP call;
6. send, close the attempt and apply the verdict.

Read phases end with a rollback before anything is written, so on SQLite no
write ever upgrades a stale read snapshot. Every statement pins the tenant.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from simple_module_db import finalize_session
from sm_records.contracts.newsletter import subscribers_by_uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.lifecycle import SENDING
from sm_newsletter.core import constants
from sm_newsletter.core.suppression import suppressed
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Campaign, CampaignRender, Send, SendAttempt
from sm_newsletter.sending import ledger, rows
from sm_newsletter.sending.classify import Verdict, classify
from sm_newsletter.sending.compose import compose
from sm_newsletter.sending.lock import HeldLock
from sm_newsletter.sending.transport import DeliveryResult, OutgoingMessage, TransportSession

__all__ = ["KIND", "Step", "deliver_one"]

logger = logging.getLogger(__name__)

KIND = "campaign"
SessionFactory = Callable[[], AsyncSession]
Clock = Callable[[], datetime]

_SKIP = Verdict("skip", False)
_INVALID = Verdict("fail", False, error_kind=constants.ERROR_INVALID_MESSAGE)


@dataclass(frozen=True)
class Step:
    spent: bool
    """Whether an SMTP attempt was made (and counted against the budget)."""
    verdict: Verdict


async def deliver_one(
    factory: SessionFactory,
    smtp: TransportSession,
    lock: HeldLock,
    *,
    tenant_id: str,
    campaign_id: int,
    secret: str,
    list_unsubscribe: bool,
    clock: Clock,
) -> Step | None:
    """One recipient of the campaign; ``None`` when there is nothing to send
    now (not ``sending``, or no due row). ``DispatchBusy`` from the lock
    propagates with nothing reserved."""
    with tenant_scope(tenant_id):
        async with factory() as session:
            return await _deliver(
                session, smtp, lock, tenant_id, campaign_id, secret, list_unsubscribe, clock
            )


async def _deliver(
    session: AsyncSession,
    smtp: TransportSession,
    lock: HeldLock,
    tenant_id: str,
    campaign_id: int,
    secret: str,
    list_unsubscribe: bool,
    clock: Clock,
) -> Step | None:
    found = await _due(session, tenant_id, campaign_id, clock())
    if found is None:
        await session.rollback()
        return None
    row, list_key, render = found
    status = await _ineligible(session, tenant_id, list_key, row)
    await session.rollback()  # end the read before any write
    if status is not None:
        await rows.skip(session, row, status=status)
        await finalize_session(session)
        return Step(False, _SKIP)
    try:
        message = compose(render, row, secret=secret, list_unsubscribe=list_unsubscribe)
    except ValueError as exc:
        refused = DeliveryResult("rejected", None, str(exc))
        await rows.record(session, row, _INVALID, refused, now=clock())
        await finalize_session(session)
        return Step(False, _INVALID)
    await lock.renew()
    attempt = await _reserve(session, lock, tenant_id, campaign_id, row, clock)
    if attempt is None:
        return Step(False, _SKIP)
    return await _send(session, smtp, attempt, row, message, clock)


async def _due(
    session: AsyncSession, tenant_id: str, campaign_id: int, now: datetime
) -> tuple[Send, str, CampaignRender] | None:
    """The next due row, the campaign's list and its render, detached from the
    session (so the reads can end), or ``None``."""
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
    session.expunge(row)
    session.expunge(render)
    return row, campaign[1], render


async def _ineligible(
    session: AsyncSession, tenant_id: str, list_key: str, row: Send
) -> rows.SkipStatus | None:
    """Why ``row`` must not be sent any more, or ``None``."""
    hits = await subscribers_by_uuid(
        session, tenant_id=tenant_id, type_key=list_key, uuids=[row.record_uuid]
    )
    hit = hits.get(row.record_uuid)
    if hit is None or hit.trashed or hit.status != "confirmed":
        return "skipped_unsubscribed"
    if await suppressed(session, tenant_id=tenant_id, emails=[row.email]):
        return "suppressed"
    return None


async def _reserve(
    session: AsyncSession,
    lock: HeldLock,
    tenant_id: str,
    campaign_id: int,
    row: Send,
    clock: Clock,
) -> SendAttempt | None:
    """Fence, claim and open the attempt in one committed transaction; the
    attempt, or ``None`` (rolled back) when the claim lost."""
    assert row.id is not None
    try:
        await lock.fence(session)
        if not await rows.claim(session, tenant_id=tenant_id, send_id=row.id, now=clock()):
            await session.rollback()
            return None
        attempt = await ledger.open_attempt(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            send_id=row.id,
            kind=KIND,
            recipient=row.email,
            now=clock(),
        )
        await finalize_session(session)
    except BaseException:
        await session.rollback()
        raise
    return attempt


async def _send(
    session: AsyncSession,
    smtp: TransportSession,
    attempt: SendAttempt,
    row: Send,
    message: OutgoingMessage,
    clock: Clock,
) -> Step:
    result = await smtp.send(message)
    await ledger.close_attempt(session, attempt, result)
    verdict = classify(result)
    await rows.record(session, row, verdict, result, now=clock())
    await finalize_session(session)
    return Step(True, verdict)
