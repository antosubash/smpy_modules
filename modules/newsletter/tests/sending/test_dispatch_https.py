"""Real mail never carries an ``http://`` snapshot (Codex C4, amendment A6).

Scheduling checks the bases only against the transport configured *then*. A
campaign scheduled on the console transport with an ``http://`` base, after
which the transport is switched to ``smtp``, is paused with ``https_required``
before any relay connection, and so is a snapshot with no ``content_base``.
"""

from __future__ import annotations

import pytest
from simple_module_db import finalize_session
from sm_newsletter.campaigns.lifecycle import split_paused
from sm_newsletter.core import constants
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import CampaignRender
from sm_newsletter.sending.deliver import deliver_one
from sm_newsletter.sending.lock import dispatch_lock
from sqlalchemy import update

from tests.support.campaign_world import campaign_row, send_rows
from tests.support.deliver_world import SECRET
from tests.support.dispatch_world import run_tick, sent_to, world
from tests.support.fake_transport import FakeTransport
from tests.support.freeze_world import due_campaign, run_freeze, schedule, subscribers
from tests.support.sending import NOW, T, attempt_rows

pytestmark = pytest.mark.unbound_tenant

HTTP = "http://news.example.org"


def _to_smtp(app) -> None:
    settings = app.state.sm_newsletter.settings
    app.state.sm_newsletter.settings = settings.model_copy(
        update={"transport": "smtp", "smtp_host": "smtp.example.org"}
    )


async def test_http_snapshot_is_paused_when_transport_turns_smtp(tmp_path):
    app, state, cid = await world(tmp_path, base_url=HTTP)
    try:
        await subscribers(state, 2)
        await schedule(app, state, cid)  # console: http is allowed
        _to_smtp(app)
        smtp = FakeTransport()

        summary = await run_tick(app, state, smtp)

        campaign = await campaign_row(state, T, cid)
        assert campaign.status == "paused"
        assert split_paused(campaign.paused_reason)[0] == constants.PAUSE_HTTPS_REQUIRED
        assert (summary.started, summary.paused, summary.spent) == (1, 1, 0)
        assert summary.stopped == "idle"
        assert await attempt_rows(state) == []
        assert smtp.opened == 0
    finally:
        await state.engine.dispose()


async def test_only_the_insecure_campaign_pauses(tmp_path):
    """A snapshot with no ``content_base`` is insecure too; the secure one is sent."""
    app, state, _ = await world(tmp_path)
    try:
        await subscribers(state, 1)
        secure = await due_campaign(state)
        bare = await due_campaign(state)
        await _secure_render(state, secure)
        _to_smtp(app)
        smtp = FakeTransport()

        summary = await run_tick(app, state, smtp)

        assert (await campaign_row(state, T, bare)).status == "paused"
        assert (await campaign_row(state, T, secure)).status == "sent"
        assert summary.paused == 1
        assert sent_to(smtp) == ["s0@example.org"]
        assert smtp.opened == 1
    finally:
        await state.engine.dispose()


async def test_deliver_one_refuses_an_insecure_snapshot(tmp_path):
    """Defence in depth: the read phase pauses it, with no claim and no attempt."""
    _, state, _ = await world(tmp_path)
    try:
        await subscribers(state, 1)
        cid = await due_campaign(state)  # seed_render: no content_base
        assert (await run_freeze(state, cid)).started
        smtp = FakeTransport()
        async with dispatch_lock(state.session_factory, holder="test") as lock:
            step = await deliver_one(
                state.session_factory,
                smtp,
                lock,
                tenant_id=T,
                campaign_id=cid,
                secret=SECRET,
                list_unsubscribe=True,
                clock=lambda: NOW,
                require_https=True,
            )
        assert step is not None and not step.spent
        assert (step.verdict.action, step.verdict.stop_tick) == ("pause", False)
        assert step.verdict.pause_code == constants.PAUSE_HTTPS_REQUIRED
        campaign = await campaign_row(state, T, cid)
        assert split_paused(campaign.paused_reason)[0] == constants.PAUSE_HTTPS_REQUIRED
        assert await attempt_rows(state) == []
        assert {row.status for row in await send_rows(state, T, cid)} == {"queued"}
        assert smtp.sent == []
    finally:
        await state.engine.dispose()


async def _secure_render(state, cid: int) -> None:
    with tenant_scope(T):
        async with state.session_factory() as db:
            await db.execute(
                update(CampaignRender)
                .where(CampaignRender.tenant_id == T, CampaignRender.campaign_id == cid)
                .values(content_base="https://news.example.org")
            )
            await finalize_session(db)
