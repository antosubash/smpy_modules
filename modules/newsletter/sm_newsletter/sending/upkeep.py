"""The dispatcher's bookkeeping around delivery (rulings S7, S12, S14).

- :func:`sending_campaigns`: every tenant's ``sending`` campaigns, oldest
  started first, the order the budget is spent in.
- :func:`recover_expired`: a ``sending`` row whose lease ran out belongs to a
  sender that died between its reservation and its result (S7). It ends
  ``failed/outcome_unknown`` and its ``pending`` attempt ``unknown``: never
  resent, and the attempt still counts against the budget.
- :func:`finish_done`: ``sending -> sent`` once no row is ``queued`` or
  ``sending`` (a row waiting for its retry is still ``queued``).
- :func:`pause_all_sending`: a relay that refuses the login pauses every
  ``sending`` campaign of every tenant (S12).

The enumerations are deliberate cross-tenant reads of ``(tenant_id, id)``
pairs, under the framework's ``all_tenants()``. Each campaign's writes then run
in its own tenant scope, in a fresh session finished with ``finalize_session``,
and every Core statement pins ``tenant_id``.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from simple_module_db import finalize_session, mark_written
from simple_module_db.tenancy import all_tenants
from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from sm_newsletter.campaigns.lifecycle import SENDING
from sm_newsletter.core import constants, tenancy
from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Campaign, Send, SendAttempt
from sm_newsletter.sending import rows

__all__ = ["finish_done", "pause_all_sending", "recover_expired", "sending_campaigns"]

SessionFactory = Callable[[], AsyncSession]
Pairs = list[tuple[str, int]]

SENT = "sent"
RECOVERED_DETAIL = "The sender stopped before recording the relay's answer"
_CAMPAIGN = Campaign.__table__  # ty: ignore[unresolved-attribute]
_SEND = Send.__table__  # ty: ignore[unresolved-attribute]
_ATTEMPT = SendAttempt.__table__  # ty: ignore[unresolved-attribute]
_OPEN = (rows.QUEUED, SENDING)  # rows that keep a campaign from finishing


async def _pairs(factory: SessionFactory, stmt: Select) -> Pairs:
    """Run a ``(tenant_id, id)`` enumeration across every tenant."""
    with all_tenants():
        async with factory() as session:
            found = (await session.execute(tenancy.all_tenants(stmt))).all()
            await finalize_session(session)
    return [(str(tenant), int(cid)) for tenant, cid in found]


async def sending_campaigns(factory: SessionFactory) -> Pairs:
    """Every tenant's ``sending`` campaigns, oldest started first."""
    stmt = (
        select(_CAMPAIGN.c.tenant_id, _CAMPAIGN.c.id)
        .where(_CAMPAIGN.c.status == SENDING)
        .order_by(_CAMPAIGN.c.started_at, _CAMPAIGN.c.id)
    )
    return await _pairs(factory, stmt)


async def recover_expired(factory: SessionFactory, *, now: datetime) -> int:
    """S7: expired ``sending`` rows -> ``failed/outcome_unknown``; how many."""
    stmt = (
        select(_SEND.c.tenant_id, _SEND.c.id)
        .where(_SEND.c.status == SENDING, _SEND.c.lease_until < now)
        .order_by(_SEND.c.id)
    )
    recovered = 0
    for tenant, send_id in await _pairs(factory, stmt):
        with tenant_scope(tenant):
            async with factory() as session:
                recovered += await _recover(session, tenant, send_id, now)
                await finalize_session(session)
    return recovered


async def _recover(session: AsyncSession, tenant: str, send_id: int, now: datetime) -> int:
    moved = (
        await session.execute(
            update(_SEND)
            .where(
                _SEND.c.id == send_id,
                _SEND.c.tenant_id == tenant,
                _SEND.c.status == SENDING,
                _SEND.c.lease_until < now,
            )
            .values(
                status="failed",
                error_kind=constants.ERROR_OUTCOME_UNKNOWN,
                last_error=RECOVERED_DETAIL,
                lease_until=None,
                retry_at=None,
                attempts=_SEND.c.attempts + 1,
            )
            .returning(_SEND.c.campaign_id)
        )
    ).scalar_one_or_none()
    mark_written(session)
    if moved is None:
        return 0
    await session.execute(
        update(_ATTEMPT)
        .where(
            _ATTEMPT.c.tenant_id == tenant,
            _ATTEMPT.c.send_id == send_id,
            _ATTEMPT.c.outcome == "pending",
        )
        .values(outcome="unknown", detail=RECOVERED_DETAIL)
    )
    await rows.bump(session, tenant_id=tenant, campaign_id=moved, failed_count=1)
    return 1


async def finish_done(factory: SessionFactory, *, now: datetime) -> int:
    """``sending -> sent`` for each campaign with no ``queued``/``sending`` row."""
    finished = 0
    for tenant, campaign_id in await sending_campaigns(factory):
        open_rows = exists().where(
            _SEND.c.tenant_id == tenant,
            _SEND.c.campaign_id == campaign_id,
            _SEND.c.status.in_(_OPEN),
        )
        stmt = (
            update(_CAMPAIGN)
            .where(
                _CAMPAIGN.c.id == campaign_id,
                _CAMPAIGN.c.tenant_id == tenant,
                _CAMPAIGN.c.status == SENDING,
                ~open_rows,
            )
            .values(
                status=SENT,
                finished_at=now,
                updated_at=now,
                revision=_CAMPAIGN.c.revision + 1,
            )
        )
        with tenant_scope(tenant):
            async with factory() as session:
                result = await session.execute(stmt)
                mark_written(session)
                await finalize_session(session)
        finished += result.rowcount  # ty: ignore[unresolved-attribute]
    return finished


async def pause_all_sending(
    factory: SessionFactory, *, code: str, detail: str, now: datetime | None = None
) -> int:
    """Pause every tenant's ``sending`` campaigns with ``code``; how many moved."""
    paused = 0
    for tenant, campaign_id in await sending_campaigns(factory):
        with tenant_scope(tenant):
            async with factory() as session:
                moved = await rows.pause_campaign(
                    session,
                    tenant_id=tenant,
                    campaign_id=campaign_id,
                    code=code,
                    detail=detail,
                    now=now or utcnow(),
                )
                await finalize_session(session)
        paused += int(moved)
    return paused
