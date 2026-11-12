"""A campaign's send rows as the dispatcher moves them (rulings S4, S7, S17, A3).

Every statement is a Core statement pinned to ``tenant_id``, and every write
is conditional on the status it expects, so a row that a cancel or another
sender moved meanwhile is left alone. The campaign's counters move in the same
transaction as the row (S17). Nothing here commits: the caller does, with
``finalize_session``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from simple_module_db import mark_written
from sqlalchemy import exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.campaigns.lifecycle import PAUSED, SENDING, paused_reason
from sm_newsletter.campaigns.transition import transition
from sm_newsletter.core import constants
from sm_newsletter.core.suppression import suppress
from sm_newsletter.models import Campaign, Send
from sm_newsletter.sending.classify import Verdict
from sm_newsletter.sending.transport import DeliveryResult

__all__ = [
    "BACKOFF",
    "LEASE",
    "MAX_ATTEMPTS",
    "SkipStatus",
    "bump",
    "claim",
    "next_row",
    "pause_campaign",
    "record",
    "skip",
]

LEASE = timedelta(minutes=10)
MAX_ATTEMPTS = 3
BACKOFF = (timedelta(minutes=5), timedelta(minutes=30))
"""The wait after the first and the second counted attempt."""

SkipStatus = Literal["suppressed", "skipped_unsubscribed"]

QUEUED = "queued"
CANCELLED = "cancelled"
_LIVE = (QUEUED, SENDING)  # what ``record`` may still finish
_RUNNING = (SENDING, PAUSED)  # a campaign whose queued rows may still go out
_SEND = Send.__table__  # ty: ignore[unresolved-attribute]
_CAMPAIGN = Campaign.__table__  # ty: ignore[unresolved-attribute]


async def next_row(
    session: AsyncSession, *, tenant_id: str, campaign_id: int, now: datetime
) -> Send | None:
    """The campaign's lowest-id ``queued`` row that is due (no ``retry_at``, or past it)."""
    stmt = (
        select(Send)
        .where(
            Send.tenant_id == tenant_id,
            Send.campaign_id == campaign_id,
            Send.status == QUEUED,
            or_(Send.retry_at.is_(None), Send.retry_at <= now),  # ty: ignore[unresolved-attribute]
        )
        .order_by(Send.id)
        .limit(1)
    )
    return (await session.execute(stmt)).scalars().first()


async def claim(session: AsyncSession, *, tenant_id: str, send_id: int, now: datetime) -> bool:
    """``queued -> sending`` with a lease, only while the campaign is ``sending`` (A3)."""
    sending = exists().where(
        _CAMPAIGN.c.id == _SEND.c.campaign_id,
        _CAMPAIGN.c.tenant_id == tenant_id,
        _CAMPAIGN.c.status == SENDING,
    )
    result = await session.execute(
        update(_SEND)
        .where(
            _SEND.c.id == send_id,
            _SEND.c.tenant_id == tenant_id,
            _SEND.c.status == QUEUED,
            sending,
        )
        .values(status=SENDING, lease_until=now + LEASE)
    )
    mark_written(session)
    return result.rowcount == 1  # ty: ignore[unresolved-attribute]


async def bump(session: AsyncSession, *, tenant_id: str, campaign_id: int, **deltas: int) -> None:
    """``col = col + n`` for each counter in ``deltas``."""
    values = {name: _CAMPAIGN.c[name] + n for name, n in deltas.items()}
    await session.execute(
        update(_CAMPAIGN)
        .where(_CAMPAIGN.c.id == campaign_id, _CAMPAIGN.c.tenant_id == tenant_id)
        .values(**values)
    )
    mark_written(session)


async def _move(
    session: AsyncSession, send: Send, from_statuses: tuple[str, ...], **values: Any
) -> bool:
    result = await session.execute(
        update(_SEND)
        .where(
            _SEND.c.id == send.id,
            _SEND.c.tenant_id == send.tenant_id,
            _SEND.c.status.in_(from_statuses),
        )
        .values(**values)
    )
    mark_written(session)
    return result.rowcount == 1  # ty: ignore[unresolved-attribute]


async def skip(session: AsyncSession, send: Send, *, status: SkipStatus) -> None:
    """Pass over a still-``queued`` row without sending; a suppressed one is counted."""
    if await _move(session, send, (QUEUED,), status=status) and status == "suppressed":
        await bump(
            session, tenant_id=send.tenant_id, campaign_id=send.campaign_id, suppressed_count=1
        )


async def record(
    session: AsyncSession, send: Send, verdict: Verdict, result: DeliveryResult, *, now: datetime
) -> None:
    """Apply ``verdict`` to the row and the campaign (S4/S17)."""
    tenant, campaign_id = send.tenant_id, send.campaign_id
    common: dict[str, Any] = {"lease_until": None, "last_error": result.detail}
    counted = {**common, "attempts": _SEND.c.attempts + 1}
    terminal = {**counted, "retry_at": None}
    counter: str | None = None
    action = verdict.action
    if action == "sent":
        values = {**terminal, "status": "sent", "sent_at": now, "last_error": None}
        counter = "sent_count"
    elif action == "retry":
        # Read off the row as claimed, written as ``attempts + 1`` in SQL: the
        # same number, because the dispatch lock serialises every writer.
        attempts = send.attempts + 1
        if attempts >= MAX_ATTEMPTS:
            values = {
                **terminal,
                "status": "failed",
                "error_kind": constants.ERROR_RETRIES_EXHAUSTED,
            }
            counter = "failed_count"
        else:
            values = {**counted, "status": QUEUED, "retry_at": now + BACKOFF[attempts - 1]}
    elif action in ("unknown", "fail"):
        values = {**terminal, "status": "failed", "error_kind": verdict.error_kind}
        counter = "failed_count"
    elif action == "bounce":
        values = {**terminal, "status": "bounced", "error_kind": verdict.error_kind}
        counter = "bounced_count"
    elif action == "pause":
        values = {**common, "status": QUEUED}
    else:
        raise ValueError(f"record() cannot apply {action!r}")
    if not await _move(session, send, _LIVE, **values):
        return
    if counter is not None:
        await bump(session, tenant_id=tenant, campaign_id=campaign_id, **{counter: 1})
    if action == "bounce":
        await suppress(
            session,
            tenant_id=tenant,
            email=send.email,
            reason=constants.REASON_HARD_BOUNCE,
            source=constants.SOURCE_SEND,
            now=now,
        )
    elif action == "pause":
        assert verdict.pause_code is not None  # noqa: S101 - narrows the type; an invariant, not input validation
        detail = " ".join(str(p) for p in (result.code, result.detail) if p not in (None, ""))
        await pause_campaign(
            session,
            tenant_id=tenant,
            campaign_id=campaign_id,
            code=verdict.pause_code,
            detail=detail,
            now=now,
        )
    if values["status"] == QUEUED:
        await _cancel_if_stranded(session, send)


async def pause_campaign(
    session: AsyncSession,
    *,
    tenant_id: str,
    campaign_id: int,
    code: str,
    detail: str = "",
    now: datetime,
) -> bool:
    """``sending -> paused`` with ``code``; whether it moved."""
    reason = paused_reason(code, detail)
    return await transition(
        session,
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        from_statuses=(SENDING,),
        values={"status": PAUSED, "paused_reason": reason, "updated_at": now},
    )


async def _cancel_if_stranded(session: AsyncSession, send: Send) -> None:
    """A row put back to ``queued`` after its campaign was cancelled mid-send
    (a cancel moves only ``queued`` rows, and this one was ``sending``) ends
    ``cancelled`` too, instead of waiting forever in a finished campaign."""
    running = exists().where(
        _CAMPAIGN.c.id == _SEND.c.campaign_id,
        _CAMPAIGN.c.tenant_id == send.tenant_id,
        _CAMPAIGN.c.status.in_(_RUNNING),
    )
    await session.execute(
        update(_SEND)
        .where(
            _SEND.c.id == send.id,
            _SEND.c.tenant_id == send.tenant_id,
            _SEND.c.status == QUEUED,
            ~running,
        )
        .values(status=CANCELLED)
    )
    mark_written(session)
