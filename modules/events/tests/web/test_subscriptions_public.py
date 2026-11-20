"""Showing a subscription publicly is a publish-right act every time it changes what is shown,
and a public subscription is never an internal one."""

from __future__ import annotations

import pytest
from sm_events.core.settings import EventsSettings
from sm_events.feeds.subscriptions import attempt, policy

from tests.support.calendars import OWNER, OWNER_P, as_user
from tests.support.subscriptions_http import SUBS, add, app_client, calendar, row, stub_launch

V, E, P, M = "events.view", "events.edit", "events.publish", "events.manage"
MANAGER_PUB = as_user("m", V, M, P)


@pytest.fixture(autouse=True)
def _no_launch(monkeypatch):
    return stub_launch(monkeypatch)


@pytest.fixture
async def http():
    async with app_client() as client:
        yield client


async def _public(http):
    cid = await calendar(http, OWNER_P, visibility="public")
    made = await add(http, cid, OWNER_P, public=True)
    assert made.status_code == 201, made.text
    return cid, made.json()


async def test_an_editor_without_publish_cannot_change_a_public_address(http):
    _, made = await _public(http)
    before = await row(http, made["id"])
    got = await http.patch(
        f"{SUBS}/{made['id']}", json={"url": "https://x.example.test/a.ics"}, headers=OWNER
    )
    assert (got.status_code, got.json()["code"]) == (403, "publish_required")
    after = await row(http, made["id"])
    assert (after.url_enc, after.url_display, after.updated_at) == (
        before.url_enc,
        before.url_display,
        before.updated_at,
    )
    ok = await http.patch(
        f"{SUBS}/{made['id']}", json={"url": "https://x.example.test/a.ics"}, headers=OWNER_P
    )
    assert ok.status_code == 200 and ok.json()["url_display"] == "https://x.example.test/…"


async def test_the_shown_label_of_a_public_subscription_needs_publish_too(http):
    _, made = await _public(http)
    assert (
        await http.patch(f"{SUBS}/{made['id']}", json={"label": "Other"}, headers=OWNER)
    ).status_code == 403
    # an edit that changes nothing shown is fine
    assert (
        await http.patch(f"{SUBS}/{made['id']}", json={"refresh_minutes": 30}, headers=OWNER)
    ).status_code == 200
    assert (
        await http.patch(f"{SUBS}/{made['id']}", json={"label": "Other"}, headers=OWNER_P)
    ).status_code == 200


async def test_the_body_cannot_publish_without_the_right(http):
    cid = await calendar(http, OWNER_P, visibility="public")
    assert (await add(http, cid, OWNER, public=True)).status_code == 403
    private = (await add(http, cid, OWNER, url="https://q.example.test/a.ics")).json()
    got = await http.patch(f"{SUBS}/{private['id']}", json={"public": True}, headers=OWNER)
    assert (got.status_code, got.json()["code"]) == (403, "publish_required")
    assert (await row(http, private["id"])).public is False


async def test_an_internal_address_cannot_be_public():
    async with app_client(allow_private_subscription_urls=True) as client:
        cid = await calendar(client, OWNER_P, visibility="public")
        refused = await add(client, cid, MANAGER_PUB, url="http://10.0.0.5:8080/a.ics", public=True)
        assert (refused.status_code, refused.json()["code"]) == (422, "url_scheme")
        # a manager's public subscription is judged, flagged and fetched as a public one
        made = (
            await add(client, cid, MANAGER_PUB, url="https://ok.example.test/a.ics", public=True)
        ).json()
        assert made["uses_internal_addresses"] is False
        assert (await row(client, made["id"])).may_use_private is False
        # an internal one made public loses the flag, and one needing it cannot be published
        internal = (await add(client, cid, MANAGER_PUB, url="http://10.0.0.5:8080/b.ics")).json()
        assert internal["uses_internal_addresses"] is True
        got = await client.patch(
            f"{SUBS}/{internal['id']}", json={"public": True}, headers=MANAGER_PUB
        )
        assert (got.status_code, got.json()["code"]) == (422, "url_scheme")
        assert (await row(client, internal["id"])).public is False


def test_a_public_subscription_is_fetched_public_only_whatever_its_flag():
    class Row:
        may_use_private = True
        public = True

    assert attempt.fetch_policy(
        EventsSettings(allow_private_subscription_urls=True), Row
    ) == policy.effective(True, may_use_private=False)
    Row.public = False
    assert (
        attempt.fetch_policy(EventsSettings(allow_private_subscription_urls=True), Row).intranet
        is True
    )
