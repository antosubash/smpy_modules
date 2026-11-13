"""Real mail routes keep retained-key capabilities and reject forgeries before SQL."""

from __future__ import annotations

import json

import pytest
from sm_newsletter.core import tokens
from sm_newsletter.web.endpoints.tracking import GIF

from tests.support.tracking_http import click_path, get, no_database, open_path, tracking_app
from tests.support.tracking_world import counters as tracking_counters
from tests.support.tracking_world import sent_campaign as tracked_campaign
from tests.support.unsub_world import ONE_CLICK, app_with, call, counters, sent_campaign, status_of

pytestmark = pytest.mark.unbound_tenant
RETIRED = ("old-host-key", " older-host-key ")


@pytest.fixture(autouse=True)
def retained_keys(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", json.dumps(RETIRED))


@pytest.mark.parametrize("secret", RETIRED)
async def test_retained_key_unsubscribe_changes_the_subscriber(secret):
    app, state, events = await app_with()
    try:
        sent = await sent_campaign(state, "default", "ada@example.org")
        token = tokens.sign(
            secret,
            purpose="u",
            tenant_id="default",
            campaign_id=sent.campaign_id,
            send_id=sent.send_id,
        )
        response = await call(app, "POST", token, data=ONE_CLICK)
        assert response.status_code == 200
        assert await status_of(state, sent) == "unsubscribed"
        assert (await counters(state, sent))["unsubscribe_count"] == 1
        assert [(event.uuid, event.status_after) for event in events] == [
            (sent.uuid, "unsubscribed")
        ]
    finally:
        await state.engine.dispose()


@pytest.mark.parametrize("secret", RETIRED)
@pytest.mark.parametrize("purpose", ["o", "c"])
async def test_retained_key_tracking_records_the_visit(secret, purpose):
    app, state = await tracking_app()
    try:
        cid, (sid,) = await tracked_campaign(state, "default")
        token = tokens.sign(
            secret, purpose=purpose, tenant_id="default", campaign_id=cid, send_id=sid
        )
        response = await get(app, open_path(token) if purpose == "o" else click_path(token))
        if purpose == "o":
            assert response.status_code == 200 and response.content == GIF
            assert (await tracking_counters(state, "default", cid))["open_total_count"] == 1
        else:
            assert response.status_code == 302 and response.headers["location"] == "https://e.org/a"
            assert (await tracking_counters(state, "default", cid))["click_total_count"] == 1
    finally:
        await state.engine.dispose()


@pytest.mark.parametrize("purpose", tokens.PURPOSES)
@pytest.mark.parametrize(
    "refusal", ["forged", "wrong_purpose", "other_host", "removed", "invalid_config"]
)
async def test_rotation_refusals_open_no_database(monkeypatch, purpose, refusal):
    app, state, _ = await app_with()
    try:
        token = tokens.sign(
            RETIRED[0], purpose=purpose, tenant_id="default", campaign_id=3, send_id=9
        )
        headers = None
        if refusal == "forged":
            token = token.rsplit(".", 1)[0] + "." + "A" * 22
        elif refusal == "wrong_purpose":
            token = tokens.sign(
                RETIRED[0],
                purpose="c" if purpose != "c" else "u",
                tenant_id="default",
                campaign_id=3,
                send_id=9,
            )
        elif refusal == "other_host":
            headers = {"x-tenant": "other", "x-tenant-source": "subdomain"}
        elif refusal == "removed":
            monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", "")
        else:
            monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", "[invalid-private-key")
        opened = no_database(monkeypatch, state)
        if purpose == "u":
            response = await call(app, "POST", token, data=ONE_CLICK, headers=headers)
            forged = await call(app, "POST", "x.1.1.AAAA", data=ONE_CLICK)
            assert response.status_code == 200 and response.content == forged.content
        else:
            response = await get(
                app, open_path(token) if purpose == "o" else click_path(token), headers
            )
            if purpose == "o":
                assert response.status_code == 200 and response.content == GIF
            else:
                assert response.status_code == 404 and response.text == "Not found"
        assert opened == []
    finally:
        await state.engine.dispose()
