"""``send_test``: admission under the dispatch lock, the ledger rows and the message."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from simple_module_db import finalize_session
from sm_newsletter.campaigns import test_send
from sm_newsletter.core.errors import (
    CampaignCancelled,
    InvalidCampaign,
    PublicBaseUrlRequired,
    SendBudgetExhausted,
    SenderNotConfigured,
    TransportUnavailable,
)
from sm_newsletter.models import Campaign, SendAttempt
from sm_newsletter.sending import ledger
from sm_newsletter.sending.transport import console
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


@pytest.fixture(autouse=True)
def _empty_outbox():
    console._outbox.clear()
    yield
    console._outbox.clear()


async def _app(*, base_url: str = BASE_URL, file=None, **settings):
    app, state = await build_app(settings={**SENDER, **settings}, file=file)
    app.state.sm.settings.public_base_url = base_url
    await seed_list(state, T)
    async with state.session_factory() as db:
        campaign = Campaign(name="c", list_type_key="news", subject="Hello", body=BODY)
        db.add(campaign)
        await finalize_session(db)
    return app, state, campaign.id


@pytest_asyncio.fixture
async def built():
    app, state, cid = await _app()
    yield app, state, cid
    await state.engine.dispose()


async def _send(app, state, cid, recipients, now=NOW):
    async with state.session_factory() as db:
        return await test_send.send_test(
            app, db, tenant_id=T, campaign_id=cid, recipients=recipients, roles=[], now=now
        )


async def _rows(state) -> list[SendAttempt]:
    async with state.session_factory() as db:
        return list((await db.execute(select(SendAttempt).order_by(SendAttempt.id))).scalars())


async def _used(state, *, at: datetime, count: int, outcome: str = "accepted") -> None:
    async with state.session_factory() as db:
        for _ in range(count):
            db.add(
                SendAttempt(
                    kind="test", recipient="x@example.org", attempted_at=at, outcome=outcome
                )
            )
        await finalize_session(db)


async def test_prefix_and_footer_and_headers(built):
    app, state, cid = built
    results = await _send(app, state, cid, ["a@example.org"])
    assert [(r.recipient, r.outcome) for r in results] == [("a@example.org", "accepted")]
    (mail,) = console.captured(T)
    assert mail.subject.startswith(test_send.TEST_SUBJECT_PREFIX)
    assert mail.subject == "[TEST] Hello"
    assert f"{BASE_URL}/newsletter/u/test" in mail.html
    assert mail.headers["List-Unsubscribe"] == f"<{BASE_URL}/newsletter/u/test>"
    assert mail.headers["From"] == "News <news@example.org>"


async def test_attempt_rows_kind_test_accepted(built):
    app, state, cid = built
    await _send(app, state, cid, ["a@example.org", "b@example.org"])
    rows = await _rows(state)
    assert [(r.kind, r.outcome, r.recipient, r.campaign_id, r.send_id) for r in rows] == [
        ("test", "accepted", "a@example.org", cid, None),
        ("test", "accepted", "b@example.org", cid, None),
    ]
    assert all(r.attempted_at == NOW and r.tenant_id == T for r in rows)


async def test_cap_two_left_three_asked_sends_none():
    app, state, cid = await _app(daily_limit=5)
    try:
        await _used(state, at=NOW - timedelta(hours=2), count=3)
        with pytest.raises(SendBudgetExhausted):
            await _send(app, state, cid, ["a@example.org", "b@example.org", "c@example.org"])
        assert console.captured(T) == []
        assert len(await _rows(state)) == 3  # no attempt rows added
        # Two fit.
        assert len(await _send(app, state, cid, ["a@example.org", "b@example.org"])) == 2
    finally:
        await state.engine.dispose()


async def test_per_minute_limit():
    app, state, cid = await _app(per_minute_limit=2)
    try:
        await _used(state, at=NOW - timedelta(seconds=30), count=1)
        await _used(state, at=NOW - timedelta(seconds=90), count=5)
        with pytest.raises(SendBudgetExhausted):
            await _send(app, state, cid, ["a@example.org", "b@example.org"])
        assert len(await _send(app, state, cid, ["a@example.org"])) == 1
        # Rejected and failed attempts do not use the budget.
        await _used(state, at=NOW, count=3, outcome="rejected")
        await _used(state, at=NOW, count=3, outcome="failed")
        with pytest.raises(SendBudgetExhausted):
            await _send(app, state, cid, ["a@example.org"])
        later = NOW + timedelta(seconds=61)
        assert len(await _send(app, state, cid, ["a@example.org"], now=later)) == 1
    finally:
        await state.engine.dispose()


@pytest.mark.parametrize("field", ["physical_address", "from_address"])
async def test_missing_physical_address_422(field):
    app, state, cid = await _app(**{field: "  "})
    try:
        with pytest.raises(SenderNotConfigured) as err:
            await _send(app, state, cid, ["a@example.org"])
        assert field in err.value.detail
        assert err.value.status == 422
        assert await _rows(state) == []
    finally:
        await state.engine.dispose()


async def test_smtp_needs_a_host():
    app, state, cid = await _app(transport="smtp", smtp_host="")
    try:
        with pytest.raises(SenderNotConfigured) as err:
            await _send(app, state, cid, ["a@example.org"])
        assert "smtp_host" in err.value.detail
    finally:
        await state.engine.dispose()


async def test_no_base_url_422():
    app, state, cid = await _app(base_url="")
    try:
        with pytest.raises(PublicBaseUrlRequired) as err:
            await _send(app, state, cid, ["a@example.org"])
        assert (err.value.status, err.value.code) == (422, "public_base_url_required")
        assert console.captured(T) == [] and await _rows(state) == []
    finally:
        await state.engine.dispose()


async def test_header_inputs_rechecked(built):
    app, state, cid = built
    async with state.session_factory() as db:
        campaign = await db.get(Campaign, cid)
        campaign.subject = "Hi\r\nBcc: victim@example.org"
        await finalize_session(db)
    with pytest.raises(InvalidCampaign) as err:
        await _send(app, state, cid, ["a@example.org"])
    assert "subject" in err.value.detail and "victim" not in err.value.detail
    app.state.sm_newsletter.settings.from_name = "News\nX"
    with pytest.raises(SenderNotConfigured) as err:
        await _send(app, state, cid, ["a@example.org"])
    assert "from_name" in err.value.detail
    assert console.captured(T) == [] and await _rows(state) == []


async def test_cancelled_campaign_refused(built):
    app, state, cid = built
    async with state.session_factory() as db:
        (await db.get(Campaign, cid)).status = "cancelled"
        await finalize_session(db)
    with pytest.raises(CampaignCancelled):
        await _send(app, state, cid, ["a@example.org"])


async def test_transport_down_rows_rejected():
    app, state, cid = await _app(transport="smtp", smtp_host="127.0.0.1", smtp_port=1)
    try:
        with pytest.raises(TransportUnavailable) as err:
            await _send(app, state, cid, ["a@example.org"])
        assert (err.value.status, err.value.code) == (502, "transport_unavailable")
        assert await ledger.attempts_since(state.session_factory, since=NOW) == 0
        assert await _rows(state) == []
    finally:
        await state.engine.dispose()


async def test_smtp_path_via_aiosmtpd(relay, make_transport, monkeypatch):
    _, recorder = relay
    monkeypatch.setattr(test_send, "transport_for", lambda settings: make_transport())
    app, state, cid = await _app(transport="smtp")
    try:
        results = await _send(app, state, cid, ["ok@example.org", "bounce@example.org"])
        assert [(r.recipient, r.outcome, r.code) for r in results] == [
            ("ok@example.org", "accepted", 250),
            ("bounce@example.org", "rejected", 550),
        ]
        assert [r.outcome for r in await _rows(state)] == ["accepted", "rejected"]
        (delivered,) = recorder.delivered
        assert b"Subject: [TEST] Hello" in delivered.original_content
        assert b"List-Unsubscribe: <https://news.example.org/newsletter/u/test>" in (
            delivered.original_content
        )
    finally:
        await state.engine.dispose()


async def test_concurrent_test_sends_never_exceed_the_cap(tmp_path):
    """Two sends of two under a cap of three: the lock serialises admission."""
    app, state, cid = await _app(daily_limit=3, file=tmp_path / "race.db")
    try:
        pair = (["a@example.org", "b@example.org"], ["c@example.org", "d@example.org"])
        outcomes = await asyncio.gather(
            *(_send(app, state, cid, rs) for rs in pair), return_exceptions=True
        )
        refused = [o for o in outcomes if isinstance(o, SendBudgetExhausted)]
        sent = [o for o in outcomes if isinstance(o, list)]
        assert (len(refused), len(sent)) == (1, 1), outcomes
        assert await ledger.attempts_since(state.session_factory, since=NOW) == 2
        assert len(console.captured(T)) == 2
    finally:
        await state.engine.dispose()
