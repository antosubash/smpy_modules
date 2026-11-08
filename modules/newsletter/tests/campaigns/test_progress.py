"""The rate, the finish estimate and the cross-tenant queue count (rulings S16, S17)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sm_newsletter.campaigns import progress
from sm_newsletter.core.settings import NewsletterSettings

from tests.support.app import build_app
from tests.support.campaign_world import seed_campaign, seed_sends
from tests.support.sending import NOW


def test_daily_rate_is_the_tighter_limit():
    assert progress.daily_rate(NewsletterSettings(daily_limit=9500, per_minute_limit=30)) == 9500
    assert progress.daily_rate(NewsletterSettings(daily_limit=100000, per_minute_limit=30)) == 43200


def test_estimate_finish_counts_the_queue_ahead():
    own = {"start": NOW, "own": 19000, "rate": 9500}
    assert progress.estimate_finish(ahead=0, **own) == NOW + timedelta(days=2)
    assert progress.estimate_finish(ahead=9500, **own) == NOW + timedelta(days=3)


@pytest.mark.unbound_tenant
async def test_queued_ahead_counts_queued_rows_of_sending_campaigns_started_earlier():
    _, state = await build_app()
    try:
        early = NOW - timedelta(hours=2)
        a = await seed_campaign(state, "default", status="sending", started_at=early)
        await seed_sends(state, "default", a, ["queued", "queued", "sent"])
        b = await seed_campaign(
            state, "other", status="sending", started_at=NOW - timedelta(hours=1)
        )
        await seed_sends(state, "other", b, ["queued"])
        paused = await seed_campaign(state, "other", status="paused", started_at=early)
        await seed_sends(state, "other", paused, ["queued"])
        factory = state.session_factory
        assert await progress.queued_ahead(factory, started_before=None) == 3
        assert await progress.queued_ahead(factory, started_before=NOW) == 3
        assert await progress.queued_ahead(factory, started_before=NOW - timedelta(hours=1)) == 2
        assert await progress.queued_ahead(factory, started_before=early) == 0
    finally:
        await state.engine.dispose()
