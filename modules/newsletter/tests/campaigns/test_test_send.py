"""``send_test``: validation, the message, the ledger rows and the budget."""

from __future__ import annotations

from datetime import timedelta

import pytest
from simple_module_db import finalize_session
from sm_newsletter.campaigns import test_send
from sm_newsletter.core.errors import (
    CampaignCancelled,
    InvalidCampaign,
    PublicBaseUrlRequired,
    SendBudgetExhausted,
    SenderNotConfigured,
)
from sm_newsletter.models import Campaign
from sm_newsletter.sending.transport import console

from tests.support.sending import BASE_URL, NOW, T, attempt_rows, make_app, send, used


async def test_prefix_and_footer_and_headers(built):
    app, state, cid = built
    results = await send(app, state, cid, ["a@example.org"])
    assert [(r.recipient, r.outcome) for r in results] == [("a@example.org", "accepted")]
    (mail,) = console.captured(T)
    assert mail.subject.startswith(test_send.TEST_SUBJECT_PREFIX)
    assert mail.subject == "[TEST] Hello"
    assert f"{BASE_URL}/newsletter/u/test" in mail.html
    assert mail.headers["List-Unsubscribe"] == f"<{BASE_URL}/newsletter/u/test>"
    assert mail.headers["From"] == "News <news@example.org>"


async def test_attempt_rows_kind_test_accepted(built):
    app, state, cid = built
    await send(app, state, cid, ["a@example.org", "b@example.org"])
    rows = await attempt_rows(state)
    assert [(r.kind, r.outcome, r.recipient, r.campaign_id, r.send_id) for r in rows] == [
        ("test", "accepted", "a@example.org", cid, None),
        ("test", "accepted", "b@example.org", cid, None),
    ]
    assert all(r.attempted_at == NOW and r.tenant_id == T for r in rows)


async def test_cap_two_left_three_asked_sends_none():
    app, state, cid = await make_app(daily_limit=5)
    try:
        await used(state, at=NOW - timedelta(hours=2), count=3)
        with pytest.raises(SendBudgetExhausted):
            await send(app, state, cid, ["a@example.org", "b@example.org", "c@example.org"])
        assert console.captured(T) == []
        assert len(await attempt_rows(state)) == 3  # no attempt rows added
        # Two fit.
        assert len(await send(app, state, cid, ["a@example.org", "b@example.org"])) == 2
    finally:
        await state.engine.dispose()


async def test_per_minute_limit():
    app, state, cid = await make_app(per_minute_limit=2)
    try:
        await used(state, at=NOW - timedelta(seconds=30), count=1)
        await used(state, at=NOW - timedelta(seconds=90), count=5)
        with pytest.raises(SendBudgetExhausted):
            await send(app, state, cid, ["a@example.org", "b@example.org"])
        assert len(await send(app, state, cid, ["a@example.org"])) == 1
        # Rejected and failed attempts do not use the budget.
        await used(state, at=NOW, count=3, outcome="rejected")
        await used(state, at=NOW, count=3, outcome="failed")
        with pytest.raises(SendBudgetExhausted):
            await send(app, state, cid, ["a@example.org"])
        later = NOW + timedelta(seconds=61)
        assert len(await send(app, state, cid, ["a@example.org"], now=later)) == 1
    finally:
        await state.engine.dispose()


@pytest.mark.parametrize("field", ["physical_address", "from_address"])
async def test_missing_physical_address_422(field):
    app, state, cid = await make_app(**{field: "  "})
    try:
        with pytest.raises(SenderNotConfigured) as err:
            await send(app, state, cid, ["a@example.org"])
        assert field in err.value.detail
        assert err.value.status == 422
        assert await attempt_rows(state) == []
    finally:
        await state.engine.dispose()


async def test_smtp_needs_a_host():
    app, state, cid = await make_app(transport="smtp", smtp_host="")
    try:
        with pytest.raises(SenderNotConfigured) as err:
            await send(app, state, cid, ["a@example.org"])
        assert "smtp_host" in err.value.detail
    finally:
        await state.engine.dispose()


async def test_no_base_url_422():
    app, state, cid = await make_app(base_url="")
    try:
        with pytest.raises(PublicBaseUrlRequired) as err:
            await send(app, state, cid, ["a@example.org"])
        assert (err.value.status, err.value.code) == (422, "public_base_url_required")
        assert console.captured(T) == [] and await attempt_rows(state) == []
    finally:
        await state.engine.dispose()


async def test_header_inputs_rechecked(built):
    app, state, cid = built
    async with state.session_factory() as db:
        campaign = await db.get(Campaign, cid)
        campaign.subject = "Hi\r\nBcc: victim@example.org"
        await finalize_session(db)
    with pytest.raises(InvalidCampaign) as err:
        await send(app, state, cid, ["a@example.org"])
    assert "subject" in err.value.detail and "victim" not in err.value.detail
    app.state.sm_newsletter.settings.from_name = "News\nX"
    with pytest.raises(SenderNotConfigured) as err:
        await send(app, state, cid, ["a@example.org"])
    assert "from_name" in err.value.detail
    assert console.captured(T) == [] and await attempt_rows(state) == []


async def test_cancelled_campaign_refused(built):
    app, state, cid = built
    async with state.session_factory() as db:
        (await db.get(Campaign, cid)).status = "cancelled"
        await finalize_session(db)
    with pytest.raises(CampaignCancelled):
        await send(app, state, cid, ["a@example.org"])
