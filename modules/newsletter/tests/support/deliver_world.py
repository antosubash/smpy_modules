"""A ``sending`` campaign with frozen rows, and helpers to deliver one recipient.

Built on :mod:`tests.support.freeze_world`: real subscribers in records, a due
campaign with its render, frozen into send rows. The app sits on a file
database (or Postgres), so a probe's session is a connection of its own.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from simple_module_db import finalize_session
from sm_newsletter.core.errors import DispatchBusy
from sm_newsletter.core.suppression import suppressed
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Send, SendAttempt
from sm_newsletter.sending.deliver import Step, deliver_one
from sm_newsletter.sending.lock import HeldLock
from sqlalchemy import select, update

from tests.support.campaign_world import campaign_row, send_rows
from tests.support.fake_transport import FakeTransport
from tests.support.freeze_world import due_campaign, run_freeze, subscribers
from tests.support.sending import NOW, T

SECRET = "deliver-secret"


async def _free() -> None:
    return None


async def _busy(*_: Any) -> None:
    raise DispatchBusy("lost")


FREE = HeldLock(_free)
LOST_LEASE = HeldLock(_busy)
FENCED_OUT = HeldLock(_free, fence=_busy)


async def sending_campaign(state: Any, n: int = 1) -> tuple[int, list[str]]:
    """``n`` confirmed subscribers frozen into a ``sending`` campaign: its id
    and their addresses."""
    emails = await subscribers(state, n)
    cid = await due_campaign(state)
    assert (await run_freeze(state, cid)).started
    return cid, emails


async def deliver(
    state: Any,
    cid: int,
    smtp: FakeTransport,
    *,
    lock: HeldLock = FREE,
    now: datetime = NOW,
    tenant: str = T,
) -> Step | None:
    return await deliver_one(
        state.session_factory,
        smtp,
        lock,
        tenant_id=tenant,
        campaign_id=cid,
        secret=SECRET,
        list_unsubscribe=True,
        clock=lambda: now,
    )


async def one_row(state: Any, cid: int) -> Send:
    (row,) = await send_rows(state, T, cid)
    return row


async def attempts(state: Any, tenant: str = T) -> list[SendAttempt]:
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            stmt = select(SendAttempt).where(SendAttempt.tenant_id == tenant)
            return list((await db.execute(stmt.order_by(SendAttempt.id))).scalars())


async def is_suppressed(state: Any, email: str) -> bool:
    with tenant_scope(T):
        async with state.session_factory() as db:
            return bool(await suppressed(db, tenant_id=T, emails=[email]))


async def counters(state: Any, cid: int) -> dict[str, int]:
    campaign = await campaign_row(state, T, cid)
    names = ("sent_count", "failed_count", "bounced_count", "suppressed_count")
    return {name: getattr(campaign, name) for name in names}


async def in_other_session(state: Any, work: Callable[[Any], Awaitable[Any]]) -> None:
    """Run ``work(db)`` in a session of its own and commit it."""
    with tenant_scope(T):
        async with state.session_factory() as db:
            await work(db)
            await finalize_session(db)


async def set_send_status(state: Any, send_id: int, status: str) -> None:
    async def write(db: Any) -> None:
        await db.execute(
            update(Send).where(Send.tenant_id == T, Send.id == send_id).values(status=status)
        )

    await in_other_session(state, write)
