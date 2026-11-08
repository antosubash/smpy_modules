"""The SMTP attempt ledger: one ``newsletter_send_attempt`` row per recipient per try.

A sender writes the row ``pending`` and commits it *immediately before* the
SMTP call (:func:`open_attempt`, then ``finalize_session``), and records the
:class:`DeliveryResult` after it (:func:`close_attempt`). A crash in between
leaves the row ``pending``, which still counts against the budget: the message
may have gone out. Every caller holds the dispatch lock
(:mod:`sm_newsletter.sending.lock`) around both.

:func:`attempts_since` is the budget's count: every tenant's rows, because the
relay's quota is the deployment's, not a tenant's. :func:`oldest_since` says
when the oldest of them leaves a window.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from simple_module_core.datetimes import aware
from simple_module_db import finalize_session
from simple_module_db.tenancy import all_tenants
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import tenancy
from sm_newsletter.models import SendAttempt
from sm_newsletter.sending.transport import DeliveryResult

__all__ = ["COUNTED_OUTCOMES", "attempts_since", "close_attempt", "oldest_since", "open_attempt"]

COUNTED_OUTCOMES = ("pending", "accepted", "unknown")
"""What uses the budget: sent, maybe sent, or not resolved yet. ``rejected``
and ``failed`` (nothing was delivered) do not."""

SessionFactory = Callable[[], AsyncSession]
_TABLE = SendAttempt.__table__  # ty: ignore[unresolved-attribute]


async def open_attempt(
    session: AsyncSession,
    *,
    tenant_id: str,
    campaign_id: int | None,
    send_id: int | None,
    kind: str,
    recipient: str,
    now: datetime,
) -> SendAttempt:
    """Add a ``pending`` attempt and flush it; the caller commits it before sending."""
    attempt = SendAttempt(
        tenant_id=tenant_id,
        campaign_id=campaign_id,
        send_id=send_id,
        kind=kind,
        recipient=recipient,
        attempted_at=now,
        outcome="pending",
    )
    session.add(attempt)
    await session.flush()
    return attempt


async def close_attempt(
    session: AsyncSession, attempt: SendAttempt, result: DeliveryResult
) -> None:
    """Record the transport's answer on ``attempt``; the caller commits."""
    attempt.outcome = result.outcome
    attempt.smtp_code = result.code
    attempt.detail = result.detail
    session.add(attempt)
    await session.flush()


async def attempts_since(session_factory: SessionFactory, *, since: datetime) -> int:
    """Counted attempts at or after ``since``, across every tenant.

    Its own short session under the framework's ``all_tenants()`` (and tagged
    for newsletter's guard): a deliberate cross-tenant count that returns a
    number, never a row.
    """
    return int(await _since(session_factory, func.count(), since) or 0)


async def oldest_since(session_factory: SessionFactory, *, since: datetime) -> datetime | None:
    """The earliest counted attempt at or after ``since``, across every tenant
    (as :func:`attempts_since`: a time, never a row), or ``None``."""
    oldest = await _since(session_factory, func.min(_TABLE.c.attempted_at), since)
    return None if oldest is None else aware(oldest)


async def _since(session_factory: SessionFactory, column: Any, since: datetime) -> Any:
    stmt = (
        select(column)
        .select_from(_TABLE)
        .where(_TABLE.c.attempted_at >= since, _TABLE.c.outcome.in_(COUNTED_OUTCOMES))
    )
    with all_tenants():
        async with session_factory() as session:
            value = (await session.execute(tenancy.all_tenants(stmt))).scalar_one()
            await finalize_session(session)
    return value
