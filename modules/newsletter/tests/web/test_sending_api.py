"""The sending routes over HTTP (rulings S2, S13, S14, S16, S17, S19)."""

from __future__ import annotations

from datetime import timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from simple_module_hosting.csrf import CSRF_HEADER
from sm_newsletter.core import constants
from sm_newsletter.core.clock import utcnow

from tests.support.app import build_app
from tests.support.campaign_world import (
    campaign_row,
    seed_campaign,
    seed_sends,
    set_columns,
)
from tests.support.records_seed import restrict_list, seed_list
from tests.support.sending import BODY, SENDER

API = f"{constants.ROUTE_PREFIX_API}/campaigns"
VIEW = {"x-perms": constants.PERM_VIEW}
SEND = {"x-perms": f"{constants.PERM_VIEW},{constants.PERM_SEND}"}
T = "default"


@pytest_asyncio.fixture
async def built():
    app, state = await build_app(settings=SENDER)
    app.state.sm.settings.public_base_url = "https://news.example.org"
    await seed_list(state, T)
    yield app, state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(built):
    app, _ = built
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _post(client, cid, action, body=None, headers=SEND):
    return await client.post(f"{API}/{cid}/{action}", json=body, headers=headers)


async def test_send_now_schedules_and_bumps_the_revision(client, built):
    _, state = built
    cid = await seed_campaign(state, T)
    res = await _post(client, cid, "send", {"expected_revision": 1})
    assert res.status_code == 200, res.text
    out = res.json()
    assert (out["status"], out["revision"]) == ("scheduled", 2)
    assert out["scheduled_at"] is not None
    assert out["paused_code"] is None and out["failed_count"] == 0


async def test_send_without_the_send_permission_403(client, built):
    _, state = built
    cid = await seed_campaign(state, T)
    res = await _post(client, cid, "send", {"expected_revision": 1}, headers=VIEW)
    assert res.status_code == 403
    assert (await campaign_row(state, T, cid)).status == "draft"


async def test_send_stale_and_not_a_draft_409(client, built):
    _, state = built
    cid = await seed_campaign(state, T)
    stale = await _post(client, cid, "send", {"expected_revision": 9})
    assert (stale.status_code, stale.json()["code"]) == (409, "stale")
    sent = await seed_campaign(state, T, status="sending", started_at=utcnow())
    res = await _post(client, sent, "send", {"expected_revision": 1})
    assert (res.status_code, res.json()["code"]) == (409, "not_a_draft")


async def test_send_empty_campaign_422(client, built):
    _, state = built
    cid = await seed_campaign(state, T, body=[])
    res = await _post(client, cid, "send", {"expected_revision": 1})
    assert (res.status_code, res.json()["code"]) == (422, "empty_campaign")


async def test_send_without_a_sender_422(client, built):
    app, state = built
    app.state.sm_newsletter.settings.from_address = ""
    cid = await seed_campaign(state, T, body=BODY)
    res = await _post(client, cid, "send", {"expected_revision": 1})
    assert (res.status_code, res.json()["code"]) == (422, "sender_not_configured")


async def test_naive_scheduled_at_422_without_the_input(client, built):
    _, state = built
    cid = await seed_campaign(state, T)
    res = await _post(
        client, cid, "send", {"expected_revision": 1, "scheduled_at": "2031-01-02T03:04:05"}
    )
    assert (res.status_code, res.json()["code"]) == (422, "invalid_campaign")
    assert "2031" not in res.text
    bad = await _post(client, cid, "send", {"expected_revision": "1"})
    assert bad.status_code == 422 and '"1"' not in bad.text


async def test_restricted_list_is_404(client, built):
    _, state = built
    cid = await seed_campaign(state, T)
    await restrict_list(state, T, "news", ["editor"])
    res = await _post(client, cid, "send", {"expected_revision": 1})
    assert res.status_code == 404
    ok = await _post(
        client, cid, "send", {"expected_revision": 1}, headers={**SEND, "x-roles": "editor"}
    )
    assert ok.status_code == 200


async def test_unschedule_returns_a_draft(client, built):
    _, state = built
    cid = await seed_campaign(state, T)
    await _post(client, cid, "send", {"expected_revision": 1})
    res = await _post(client, cid, "unschedule", {"expected_revision": 2})
    assert res.status_code == 200, res.text
    assert (res.json()["status"], res.json()["scheduled_at"]) == ("draft", None)


async def test_pause_resume_cancel(client, built):
    _, state = built
    cid = await seed_campaign(state, T, status="sending", started_at=utcnow())
    paused = await _post(client, cid, "pause")
    assert paused.status_code == 200, paused.text
    assert (paused.json()["status"], paused.json()["paused_code"]) == ("paused", "manual")
    resumed = await _post(client, cid, "resume")
    assert (resumed.json()["status"], resumed.json()["paused_code"]) == ("sending", None)
    cancelled = await _post(client, cid, "cancel")
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["finished_at"] is not None


@pytest.mark.parametrize("action", ["pause", "resume", "cancel"])
async def test_actions_from_sent_409(client, built, action):
    _, state = built
    cid = await seed_campaign(state, T, status="sent", started_at=utcnow())
    res = await _post(client, cid, action)
    assert (res.status_code, res.json()["code"]) == (409, "invalid_transition")


@pytest.mark.unbound_tenant
async def test_another_tenants_campaign_is_404_and_untouched():
    app, state = await build_app(multi=True, settings=SENDER)
    app.state.sm.settings.public_base_url = "https://news.example.org"
    try:
        await seed_list(state, "A")
        await seed_list(state, "B")
        other = await seed_campaign(state, "B", status="sending", started_at=utcnow())
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            headers = {**SEND, "x-tenant": "A"}
            for action in ("pause", "cancel", "resume"):
                assert (await _post(c, other, action, headers=headers)).status_code == 404
            assert (
                await _post(c, other, "send", {"expected_revision": 1}, headers=headers)
            ).status_code == 404
            assert (await c.get(f"{API}/{other}/progress", headers=headers)).status_code == 404
            assert (await c.get(f"{API}/{other}/estimate", headers=headers)).status_code == 404
        assert (await campaign_row(state, "B", other)).status == "sending"
    finally:
        await state.engine.dispose()


async def test_progress_counts_each_status(client, built):
    _, state = built
    cid = await seed_campaign(state, T, status="paused", started_at=utcnow())
    statuses = ["queued"] * 2 + ["sending", "sent", "sent", "sent", "failed", "bounced"]
    statuses += ["suppressed", "skipped_unsubscribed", "cancelled"]
    await seed_sends(state, T, cid, statuses)
    await set_columns(state, T, cid, recipient_count=11, paused_reason="smtp_rejected|550 no")
    res = await client.get(f"{API}/{cid}/progress", headers=VIEW)
    assert res.status_code == 200, res.text
    out = res.json()
    assert (out["recipients"], out["queued"], out["sending"], out["sent"]) == (11, 2, 1, 3)
    assert (out["failed"], out["bounced"], out["suppressed"], out["skipped"]) == (1, 1, 1, 1)
    assert (out["cancelled"], out["status"]) == (1, "paused")
    assert (out["paused_code"], out["paused_detail"]) == ("smtp_rejected", "550 no")
    assert out["daily_rate"] == 100
    assert out["estimated_finish"] is None


async def test_progress_of_a_sending_campaign_has_an_estimate(client, built):
    _, state = built
    cid = await seed_campaign(state, T, status="sending", started_at=utcnow())
    await seed_sends(state, T, cid, ["queued"] * 4)
    out = (await client.get(f"{API}/{cid}/progress", headers=VIEW)).json()
    assert out["estimated_finish"] is not None


@pytest.mark.unbound_tenant
async def test_estimate_overlap_and_shape():
    app, state = await build_app(multi=True, settings=SENDER)
    try:
        await seed_list(state, "A")
        await seed_list(state, "B")
        mine = await seed_campaign(state, "A")
        headers = {**SEND, "x-tenant": "A"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            quiet = (await c.get(f"{API}/{mine}/estimate", headers=headers)).json()
            assert quiet["overlaps"] is False and quiet["recipients"] == 0
            busy = await seed_campaign(state, "B", status="sending", started_at=utcnow())
            await seed_sends(state, "B", busy, ["queued"] * 5)
            at = (utcnow() + timedelta(days=1)).isoformat()
            res = await c.get(f"{API}/{mine}/estimate", params={"at": at}, headers=headers)
            out = res.json()
            assert set(out) == {"recipients", "estimated_finish", "overlaps", "daily_rate"}
            assert out["overlaps"] is True
            for bad in ("nonsense", "2031-01-01T00:00:00"):
                r = await c.get(f"{API}/{mine}/estimate", params={"at": bad}, headers=headers)
                assert (r.status_code, r.json()["code"]) == (422, "invalid_campaign")
                assert bad not in r.text
    finally:
        await state.engine.dispose()


async def test_send_without_the_csrf_token_403():
    app, state = await build_app(settings=SENDER, session=True)
    app.state.sm.settings.public_base_url = "https://news.example.org"
    try:
        await seed_list(state, T)
        cid = await seed_campaign(state, T)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            res = await c.post(f"{API}/{cid}/send", json={"expected_revision": 1}, headers=SEND)
            assert res.status_code == 403
            token = (await c.get("/token")).json()["token"]
            ok = await c.post(
                f"{API}/{cid}/send",
                json={"expected_revision": 1},
                headers={**SEND, CSRF_HEADER: token},
            )
            assert ok.status_code == 200, ok.text
    finally:
        await state.engine.dispose()


async def _create(client):
    res = await client.post(
        API,
        json={"name": "n", "list_type_key": "news"},
        headers={"x-perms": "newsletter.view,newsletter.edit"},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_detail_holds_the_sending_fields(client):
    created = await _create(client)
    got = (await client.get(f"{API}/{created['id']}", headers=VIEW)).json()
    assert got["scheduled_at"] is None and got["started_at"] is None and got["finished_at"] is None
    assert got["paused_code"] is None and got["paused_detail"] is None
    for key in ("failed_count", "bounced_count", "suppressed_count", "unsubscribe_count"):
        assert got[key] == 0


async def test_estimate_far_future_at_is_422_not_500(client, built):
    _, state = built
    cid = await seed_campaign(state, T)
    for bad in ("9999-12-31T00:00:00+00:00", "2000-01-01T00:00:00+00:00"):
        res = await client.get(f"{API}/{cid}/estimate", params={"at": bad}, headers=SEND)
        assert (res.status_code, res.json()["code"]) == (422, "invalid_campaign")
        assert "9999" not in res.text
