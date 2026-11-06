"""Deliver one recipient of a ``sending`` campaign (rulings S4, S6, S7; A3, A4).

The caller holds the dispatch lock. Per recipient, in this order:

1. read the campaign (a shortcut: the claim decides) and its next due row; on
   the ``smtp`` transport a snapshot whose bases are not both ``https://``
   pauses the campaign (``https_required``) with no claim and no attempt (the
   dispatcher pauses those before it connects; this is the backstop);
2. re-check the subscriber (still confirmed in records, not suppressed): an
   ineligible row is skipped with no SMTP call and no ledger row, and a list
   that is gone (deleted, or no longer a list) pauses the campaign with
   ``list_unavailable``, as freeze does;
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
from typing import Literal

from simple_module_db import finalize_session
from sm_records.contracts.newsletter import (
    SubscriberFilterError,
    subscribers_by_uuid,
    subscription_lists,
)
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.checks import bases_https
from sm_newsletter.core import constants
from sm_newsletter.core.suppression import suppressed
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import CampaignRender, Send, SendAttempt
from sm_newsletter.sending import ledger, rows
from sm_newsletter.sending.classify import Verdict, classify
from sm_newsletter.sending.compose import compose
from sm_newsletter.sending.due import next_due
from sm_newsletter.sending.lock import HeldLock
from sm_newsletter.sending.transport import DeliveryResult, OutgoingMessage, TransportSession
from sm_newsletter.tracking.rewrite import TRACKING_OFF, Tracking

__all__ = ["KIND", "Step", "deliver_one"]

logger = logging.getLogger(__name__)

KIND = "campaign"
SessionFactory = Callable[[], AsyncSession]
Clock = Callable[[], datetime]

_SKIP = Verdict("skip", False)
_INVALID = Verdict("fail", False, error_kind=constants.ERROR_INVALID_MESSAGE)
# Tenant-local: the campaign pauses, and the tick goes on with the others.
_NO_LIST = Verdict("pause", False, pause_code=constants.PAUSE_LIST_UNAVAILABLE)
_LIST_GONE = "list_unavailable"
_INSECURE = Verdict("pause", False, pause_code=constants.PAUSE_HTTPS_REQUIRED)


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
    require_https: bool = False,
    tracking: Tracking = TRACKING_OFF,
) -> Step | None:
    """One recipient of the campaign; ``None`` when there is nothing to send
    now (not ``sending``, no due row, or the claim lost to a pause, a cancel
    or another sender: nothing was skipped). ``tracking`` fills the snapshot's
    link and pixel placeholders (the tick's settings, B7). ``require_https`` (the ``smtp``
    transport) refuses a snapshot whose bases are not both ``https://``.
    ``DispatchBusy`` from the lock propagates with nothing reserved."""
    with tenant_scope(tenant_id):
        async with factory() as session:
            found = await next_due(session, tenant_id, campaign_id, clock())
            if found is None:
                await session.rollback()
                return None
            if require_https and not bases_https(found[2].content_base, found[2].public_base):
                await session.rollback()  # end the read before any write
                await _pause(session, tenant_id, campaign_id, constants.PAUSE_HTTPS_REQUIRED, clock)
                return Step(False, _INSECURE)
            return await _deliver(
                session,
                smtp,
                lock,
                found,
                (tenant_id, campaign_id, secret, list_unsubscribe, tracking),
                clock,
            )


async def _pause(
    session: AsyncSession, tenant_id: str, campaign_id: int, code: str, clock: Clock
) -> None:
    await rows.pause_campaign(
        session, tenant_id=tenant_id, campaign_id=campaign_id, code=code, now=clock()
    )
    await finalize_session(session)


async def _deliver(
    session: AsyncSession,
    smtp: TransportSession,
    lock: HeldLock,
    found: tuple[Send, str, CampaignRender, dict[int, str]],
    params: tuple[str, int, str, bool, Tracking],
    clock: Clock,
) -> Step | None:
    tenant_id, campaign_id, secret, list_unsubscribe, tracking = params
    row, list_key, render, links = found
    status = await _ineligible(session, tenant_id, list_key, row)
    await session.rollback()  # end the read before any write
    if status == _LIST_GONE:
        await _pause(session, tenant_id, campaign_id, constants.PAUSE_LIST_UNAVAILABLE, clock)
        return Step(False, _NO_LIST)
    if status is not None:
        await rows.skip(session, row, status=status)
        await finalize_session(session)
        return Step(False, _SKIP)
    try:
        message = compose(
            render,
            row,
            secret=secret,
            list_unsubscribe=list_unsubscribe,
            tracking=tracking,
            links=links,
        )
    except ValueError as exc:
        refused = DeliveryResult("rejected", None, str(exc))
        await rows.record(session, row, _INVALID, refused, now=clock())
        await finalize_session(session)
        return Step(False, _INVALID)
    await lock.renew()
    attempt = await _reserve(session, lock, tenant_id, campaign_id, row, clock)
    if attempt is None:  # the claim lost: the row or the campaign moved
        return None
    return await _send(session, smtp, attempt, row, message, clock)


async def _ineligible(
    session: AsyncSession, tenant_id: str, list_key: str, row: Send
) -> rows.SkipStatus | Literal["list_unavailable"] | None:
    """Why ``row`` must not be sent any more, or ``None``. The list gone (the
    type deleted, or no longer a list) is about the campaign, not the
    subscriber: :data:`_LIST_GONE`, and the campaign pauses as freeze's does."""
    if list_key not in await subscription_lists(session, tenant_id=tenant_id):
        return _LIST_GONE
    try:
        hits = await subscribers_by_uuid(
            session, tenant_id=tenant_id, type_key=list_key, uuids=[row.record_uuid]
        )
    except SubscriberFilterError:  # de-listed since the check above
        return _LIST_GONE
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
