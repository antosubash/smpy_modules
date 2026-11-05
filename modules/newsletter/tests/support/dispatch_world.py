"""Running the dispatcher tick against a file database (or Postgres).

Every tick runs with no tenant bound, as the worker does, so the tests using
these helpers are ``unbound_tenant`` and the helpers bind what they seed.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from simple_module_db import finalize_session
from simple_module_db.tenancy import all_tenants
from sm_newsletter.core import constants, tenancy, tokens
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Campaign, SendAttempt
from sm_newsletter.sending.dispatch import TickSummary, tick
from sm_newsletter.sending.ledger import COUNTED_OUTCOMES
from sqlalchemy import select

from tests.support.deliver_world import SECRET
from tests.support.fake_transport import FakeTransport
from tests.support.freeze_world import due_campaign, run_freeze, subscribers
from tests.support.records_seed import seed_list
from tests.support.sending import NOW, T, make_app

DAY = timedelta(hours=24)


async def world(tmp_path: Path, **settings: Any) -> tuple[Any, Any, int]:
    """``make_app`` on a file database with ``settings``: the app, its state
    and a draft campaign's id (for test sends)."""
    with tenant_scope(T):
        return await make_app(file=tmp_path / "dispatch.db", **settings)


async def run_tick(
    app: Any, state: Any, smtp: FakeTransport, *, at: datetime = NOW, **kw: Any
) -> TickSummary:
    return await tick(
        state.session_factory,
        settings=app.state.sm_newsletter.settings,
        secret=SECRET,
        transport=smtp,
        clock=lambda: at,
        **kw,
    )


async def due(state: Any, n: int, *, tenant: str = T) -> tuple[int, list[str]]:
    """``n`` subscribers ``<tenant><i>@example.org`` and a due ``scheduled``
    campaign of ``tenant``; the list ``news`` is seeded first outside ``default``."""
    if tenant != T:
        await seed_list(state, tenant)
    emails = await subscribers(state, n, tenant=tenant, prefix=tenant)
    return await due_campaign(state, tenant), emails


async def started(state: Any, n: int, *, tenant: str = T, at: datetime) -> tuple[int, list[str]]:
    """As :func:`due`, frozen into ``sending`` with ``started_at = at``."""
    cid, emails = await due(state, n, tenant=tenant)
    assert (await run_freeze(state, cid, tenant=tenant, now=at)).started
    return cid, emails


def sent_to(smtp: FakeTransport) -> list[str]:
    return [message.to for message in smtp.sent]


def token_of(message: Any) -> tokens.SendToken | None:
    """The verified token of the unsubscribe link in ``message``'s text."""
    raw = message.text.split(constants.UNSUBSCRIBE_PREFIX, 1)[1].split()[0]
    return tokens.parse(SECRET, raw)


async def counted_times(state: Any) -> list[datetime]:
    """Every tenant's counted attempts' times, oldest first."""
    table = SendAttempt.__table__  # ty: ignore[unresolved-attribute]
    stmt = (
        select(table.c.attempted_at)
        .where(table.c.outcome.in_(COUNTED_OUTCOMES))
        .order_by(table.c.attempted_at)
    )
    with all_tenants():
        async with state.session_factory() as db:
            found = (await db.execute(tenancy.all_tenants(stmt))).scalars().all()
    return [_aware(at) for at in found]


def _aware(at: datetime) -> datetime:
    return at if at.tzinfo is not None else at.replace(tzinfo=NOW.tzinfo)


def busiest_day(times: Sequence[datetime]) -> int:
    """The most attempts any rolling 24 h window holds."""
    return max((sum(1 for t in times if start <= t < start + DAY) for start in times), default=0)


async def lifecycle_action(state: Any, action: Any, cid: int, tenant: str = T) -> Campaign:
    """``lifecycle.pause``/``resume``/``cancel`` in a committed session of its own."""
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            campaign = await action(db, tenant_id=tenant, campaign_id=cid, roles=[], now=NOW)
            await finalize_session(db)
            return campaign
