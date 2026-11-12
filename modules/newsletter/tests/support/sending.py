"""A test-send fixture world: an app with a configured console sender, the
list ``news`` and one draft campaign, plus ledger helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from simple_module_db import finalize_session
from sm_newsletter.campaigns import test_send
from sm_newsletter.models import Campaign, SendAttempt
from sqlalchemy import select

from tests.support.app import build_app
from tests.support.records_seed import seed_list

T = "default"
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)
BASE_URL = "https://news.example.org"
SENDER = {
    "transport": "console",
    "from_address": "news@example.org",
    "from_name": "News",
    "physical_address": "1 Main Street, Springfield",
    "daily_limit": 100,
    "per_minute_limit": 100,
}
BODY = [{"type": "Divider", "props": {"id": "a"}}]


async def make_app(*, base_url: str = BASE_URL, file=None, **settings):
    app, state = await build_app(settings={**SENDER, **settings}, file=file)
    app.state.sm.settings.public_base_url = base_url
    await seed_list(state, T)
    async with state.session_factory() as db:
        campaign = Campaign(name="c", list_type_key="news", subject="Hello", body=BODY)
        db.add(campaign)
        await finalize_session(db)
    return app, state, campaign.id


async def send(app, state, cid, recipients, now=NOW, allowed=None, submitted=None):
    """``send_test`` with every recipient vouched for unless ``allowed`` says otherwise."""
    async with state.session_factory() as db:
        return await test_send.send_test(
            app,
            db,
            tenant_id=T,
            campaign_id=cid,
            recipients=recipients,
            allowed=recipients if allowed is None else allowed,
            roles=[],
            now=now,
            submitted=submitted,
        )


async def attempt_rows(state) -> list[SendAttempt]:
    async with state.session_factory() as db:
        return list((await db.execute(select(SendAttempt).order_by(SendAttempt.id))).scalars())


async def used(state, *, at: datetime, count: int, outcome: str = "accepted") -> None:
    async with state.session_factory() as db:
        for _ in range(count):
            db.add(
                SendAttempt(
                    kind="test", recipient="x@example.org", attempted_at=at, outcome=outcome
                )
            )
        await finalize_session(db)
