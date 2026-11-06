"""Due campaigns, their subscribers and freezer helpers for the freeze tests.

Every helper binds the tenant it is given, so the tests run bound (to
``default``) or ``unbound_tenant`` alike. The app sits on a file database (or
Postgres): the fence tests interleave sessions.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any

from simple_module_db import finalize_session
from sm_newsletter.campaigns import lifecycle
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.sending import freeze as freezing

from tests.support.campaign_world import campaign_row, seed_campaign, seed_render, send_rows
from tests.support.records_seed import seed_subscriber
from tests.support.sending import NOW, T, make_app

DUE = NOW - timedelta(minutes=1)


async def world(tmp_path: Path) -> tuple[Any, Any, int]:
    """``make_app`` on a file database: the app, its state and a draft's id."""
    with tenant_scope(T):
        return await make_app(file=tmp_path / "freeze.db")


async def due_campaign(state: Any, tenant: str = T, *, list_key: str = "news", due_at=DUE) -> int:
    """A ``scheduled`` campaign of ``tenant``, due at ``due_at`` (a minute ago),
    with its render."""
    cid = await seed_campaign(
        state, tenant, status="scheduled", list_key=list_key, scheduled_at=due_at
    )
    await seed_render(state, tenant, cid)
    return cid


async def subscribers(
    state: Any, n: int, *, tenant: str = T, key: str = "news", prefix: str = "s"
) -> list[str]:
    """``n`` confirmed subscribers ``<prefix><i>@example.org``; their addresses."""
    emails = [f"{prefix}{i}@example.org" for i in range(n)]
    for email in emails:
        await seed_subscriber(state, tenant, email, "confirmed", key)
    return emails


def pinned(now=NOW):
    """A clock that always says ``now``."""
    return lambda: now


async def run_freeze(
    state: Any, cid: int, *, tenant: str = T, now=NOW, clock=None
) -> freezing.FreezeResult:
    with tenant_scope(tenant):
        return await freezing.freeze(
            state.session_factory,
            tenant_id=tenant,
            campaign_id=cid,
            now=now,
            clock=clock or pinned(now),
        )


async def start_due(state: Any, now=NOW) -> int:
    return await freezing.start_due(state.session_factory, now=now, clock=pinned(now))


async def statuses(state: Any, cid: int, tenant: str = T) -> Counter[str]:
    return Counter(row.status for row in await send_rows(state, tenant, cid))


async def emails(state: Any, cid: int, tenant: str = T) -> list[str]:
    return sorted(row.email for row in await send_rows(state, tenant, cid))


async def unschedule(state: Any, cid: int, tenant: str = T) -> None:
    revision = (await campaign_row(state, tenant, cid)).revision
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            await lifecycle.unschedule(
                db, tenant_id=tenant, campaign_id=cid, roles=[], expected_revision=revision
            )
            await finalize_session(db)


async def schedule(app: Any, state: Any, cid: int, tenant: str = T, *, when=None) -> None:
    """Schedule ``cid`` at ``when`` (``None``: due now, at :data:`DUE`)."""
    revision = (await campaign_row(state, tenant, cid)).revision
    with tenant_scope(tenant):
        async with state.session_factory() as db:
            await lifecycle.schedule(
                app,
                db,
                tenant_id=tenant,
                campaign_id=cid,
                roles=[],
                expected_revision=revision,
                scheduled_at=when,
                now=DUE,
            )
            await finalize_session(db)


def gate_page(monkeypatch: Any, page: int, before: Any) -> None:
    """Run ``await before()`` when the freezer asks for page ``page`` (1-based),
    then read it. ``before`` may raise to crash the freezer there."""
    real = freezing.iter_subscribers
    calls = 0

    async def gated(session: Any, **kw: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == page:
            await before()
        return await real(session, **kw)

    monkeypatch.setattr(freezing, "iter_subscribers", gated)


class Pause:
    """Two events: ``reached`` once the freezer waits, ``go`` to let it on."""

    def __init__(self) -> None:
        self.reached, self.go = asyncio.Event(), asyncio.Event()

    async def __call__(self) -> None:
        self.reached.set()
        await self.go.wait()
