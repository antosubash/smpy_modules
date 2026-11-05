"""Cancel of a campaign that never started takes the campaign row first (M4, N1).

``unschedule`` and a freeze page lock the campaign row and then its send rows;
a cancel of a never-started campaign must do the same, or Postgres reports a
deadlock. Each test parks the other transaction while it holds the campaign
row, starts the cancel, and lets the other go once the cancel has issued its
campaign ``UPDATE``. On SQLite one writer holds the whole database, so the
tests only check the outcome there.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator
from typing import Any

import pytest
from simple_module_db import finalize_session
from sm_newsletter.campaigns import lifecycle
from sm_newsletter.core.errors import NewsletterError
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Campaign
from sm_newsletter.sending import freeze as freezing
from sm_newsletter.sending import freeze_pages
from sqlalchemy import event, select, update
from sqlalchemy.exc import DBAPIError

from tests.pg_support import USING_POSTGRES
from tests.support.campaign_world import campaign_row, seed_sends, send_rows
from tests.support.freeze_world import due_campaign, run_freeze, statuses, subscribers, world
from tests.support.sending import NOW, T

ROUNDS = 5
WAIT_S = 5.0
SEND_TABLE = "newsletter_send"
SETTLE_S = 0.3  # let the cancel's UPDATE reach the database and block


class _Hold:
    """The other transaction parks holding the campaign row until the cancel's
    campaign ``UPDATE`` is issued."""

    def __init__(self) -> None:
        self.parked = asyncio.Event()
        self.cancel_issued = asyncio.Event()

    async def park(self) -> None:
        self.parked.set()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.cancel_issued.wait(), WAIT_S)
        await asyncio.sleep(SETTLE_S)


@contextlib.contextmanager
def _watch_cancel(state: Any, hold: _Hold) -> Iterator[None]:
    def on_execute(conn, cursor, statement, params, context, executemany):
        text = statement.lstrip().upper()
        if hold.parked.is_set() and text.startswith("UPDATE NEWSLETTER_CAMPAIGN SET"):
            hold.cancel_issued.set()

    sync_engine = state.engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", on_execute)
    try:
        yield
    finally:
        event.remove(sync_engine, "before_cursor_execute", on_execute)


@pytest.fixture
async def built(tmp_path):
    app, state, _ = await world(tmp_path)
    yield app, state
    await state.engine.dispose()


async def _cancel(state: Any, cid: int, hold: _Hold) -> str:
    await asyncio.wait_for(hold.parked.wait(), WAIT_S)
    try:
        with tenant_scope(T):
            async with state.session_factory() as db:
                await lifecycle.cancel(db, tenant_id=T, campaign_id=cid, roles=[], now=NOW)
                await finalize_session(db)
    except NewsletterError as exc:
        return f"{exc.status} {exc.code}"
    return "won"


async def _unschedule(state: Any, cid: int) -> str:
    revision = (await campaign_row(state, T, cid)).revision
    try:
        with tenant_scope(T):
            async with state.session_factory() as db:
                await lifecycle.unschedule(
                    db, tenant_id=T, campaign_id=cid, roles=[], expected_revision=revision
                )
                await finalize_session(db)
    except NewsletterError as exc:
        return f"{exc.status} {exc.code}"
    return "won"


async def test_cancel_and_unschedule_never_deadlock(built, monkeypatch):
    _, state = built
    hold = _Hold()
    real_drop = lifecycle.drop_render

    async def parked_drop(session, **kw):
        await hold.park()  # unschedule holds the campaign row, before its DELETE
        await real_drop(session, **kw)

    monkeypatch.setattr(lifecycle, "drop_render", parked_drop)
    with _watch_cancel(state, hold):
        for _ in range(ROUNDS):
            hold.__init__()
            cid = await due_campaign(state)
            await seed_sends(state, T, cid, ["queued", "queued"])
            outcomes = await asyncio.gather(
                _unschedule(state, cid), _cancel(state, cid, hold), return_exceptions=True
            )
            errors = [o for o in outcomes if isinstance(o, BaseException)]
            assert not errors, f"a transaction failed: {errors!r}"
            assert hold.cancel_issued.is_set()
            assert outcomes == ["won", "409 invalid_transition"]
            assert (await campaign_row(state, T, cid)).status == "draft"
            assert await send_rows(state, T, cid) == []


async def test_cancel_waits_for_a_freeze_page_and_cancels_its_rows(built, monkeypatch):
    _, state = built
    monkeypatch.setattr(freezing, "PAGE", 2)
    await subscribers(state, 4)
    cid = await due_campaign(state)
    hold = _Hold()
    real_insert = freeze_pages.insert_ignore
    pages = 0

    async def parked_insert(session, *args, **kw):
        nonlocal pages
        out = await real_insert(session, *args, **kw)
        pages += 1
        if pages == 2:
            await hold.park()  # page 2 holds the campaign row, its rows uncommitted
        return out

    monkeypatch.setattr(freeze_pages, "insert_ignore", parked_insert)
    with _watch_cancel(state, hold):
        result, outcome = await asyncio.gather(
            run_freeze(state, cid), _cancel(state, cid, hold), return_exceptions=True
        )
    assert hold.cancel_issued.is_set()
    assert outcome == "won"
    if USING_POSTGRES:
        # The waiting cancel is queued on the row ahead of the freezer's next
        # renewal; SQLite has no such queue and may let the freezer publish
        # first, after which the cancel takes the started path.
        assert result == freezing.FreezeResult(False, 0, 0)
    assert (await campaign_row(state, T, cid)).status == "cancelled"
    assert await statuses(state, cid) == {"cancelled": 4}


@pytest.mark.skipif(not USING_POSTGRES, reason="row locks and the EPQ re-check are Postgres's")
async def test_cancel_started_meanwhile_keeps_no_campaign_lock(built):
    """The never-started ``UPDATE`` waits on a publish, then refuses: the
    started path must begin with the campaign row free (B1), send rows first."""
    _, state = built
    cid = await due_campaign(state)
    (sid,) = await seed_sends(state, T, cid, ["queued"])
    hold, probes = _Hold(), []

    async def probe() -> None:
        with tenant_scope(T):
            async with state.session_factory() as other:
                stmt = select(Campaign.id).where(Campaign.tenant_id == T, Campaign.id == cid)
                try:
                    await other.execute(stmt.with_for_update(nowait=True))
                    probes.append("free")
                except DBAPIError:
                    probes.append("locked")
                await other.rollback()

    async def publish() -> None:
        with tenant_scope(T):
            async with state.session_factory() as db:
                await db.execute(
                    update(Campaign)
                    .where(Campaign.tenant_id == T, Campaign.id == cid)
                    .values(status="sending", started_at=NOW)
                )
                await hold.park()  # uncommitted until cancel's UPDATE waits on it
                await finalize_session(db)

    async def cancel() -> str:
        await asyncio.wait_for(hold.parked.wait(), WAIT_S)
        with tenant_scope(T):
            async with state.session_factory() as db:
                real = db.execute

                async def execute(stmt, *args, **kw):
                    if getattr(getattr(stmt, "table", None), "name", None) == SEND_TABLE:
                        await probe()  # just before the fallback's send UPDATE
                    return await real(stmt, *args, **kw)

                db.execute = execute  # ty: ignore[invalid-assignment]
                campaign = await lifecycle.cancel(
                    db, tenant_id=T, campaign_id=cid, roles=[], now=NOW
                )
                await finalize_session(db)
                return campaign.status

    with _watch_cancel(state, hold):
        outcomes = await asyncio.gather(publish(), cancel(), return_exceptions=True)
    errors = [o for o in outcomes if isinstance(o, BaseException)]
    assert not errors, f"a transaction failed: {errors!r}"
    assert hold.cancel_issued.is_set()
    assert probes == ["free"]
    assert outcomes[1] == "cancelled"
    after = await campaign_row(state, T, cid)
    assert (after.status, after.started_at is not None) == ("cancelled", True)
    assert [(r.id, r.status) for r in await send_rows(state, T, cid)] == [(sid, "cancelled")]
