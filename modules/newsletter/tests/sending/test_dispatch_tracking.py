"""The tick composes with the settings it started with (T5, B7); SQLite file and Postgres."""

from __future__ import annotations

import pytest

from tests.support.dispatch_world import run_tick, started
from tests.support.fake_transport import FakeTransport
from tests.support.freeze_world import due_campaign, run_freeze
from tests.support.sending import NOW
from tests.support.tracking_world import track_render

pytestmark = pytest.mark.unbound_tenant


@pytest.fixture
async def built(tmp_path):
    from tests.support.dispatch_world import world

    app, state, _ = await world(tmp_path, tracking_opens=True, tracking_clicks=True)
    yield app, state
    await state.engine.dispose()


async def _tracked(state, n):
    cid, _ = await started(state, n, at=NOW)
    await track_render(state, cid)
    return cid


def _tracked_message(m) -> bool:
    return "/newsletter/o/" in m.html and "/newsletter/c/" in m.html


async def test_tick_follows_tracking_settings(built):
    app, state = built
    await _tracked(state, 2)
    smtp = FakeTransport()

    await run_tick(app, state, smtp, deadline_s=50)
    assert smtp.sent and all(_tracked_message(m) for m in smtp.sent)

    settings = app.state.sm_newsletter.settings
    settings.tracking_opens = False
    settings.tracking_clicks = False
    cid = await due_campaign(state)  # a second issue to the same subscribers
    assert (await run_freeze(state, cid, now=NOW)).started
    await track_render(state, cid)
    later = FakeTransport()
    await run_tick(app, state, later)
    assert later.sent
    for m in later.sent:
        assert "/newsletter/o/" not in m.html and "/newsletter/c/" not in m.html
        assert 'href="https://example.com/story?a=1&amp;b=2"' in m.html


async def test_settings_fixed_for_one_tick(built):
    app, state = built
    await _tracked(state, 3)
    settings = app.state.sm_newsletter.settings

    async def flip(_msg) -> None:
        settings.tracking_opens = False
        settings.tracking_clicks = False

    smtp = FakeTransport(on_send=flip)
    await run_tick(app, state, smtp)

    assert len(smtp.sent) == 3
    assert all(_tracked_message(m) for m in smtp.sent)
