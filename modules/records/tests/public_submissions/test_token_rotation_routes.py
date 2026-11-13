"""Old public capabilities still complete real writes after a key rotation."""

import json
import time

import pytest
from sm_records.public_submissions import links
from sm_records.public_submissions.tokens import host_secret, sign_form

from tests.support.newsletter_http import LIST, follow, links_in, signup, subscriber
from tests.support.submissions_http import contact_type, load, records_of, send
from tests.support.tenancy_support import statements

CURRENT = "replacement-records-key"


def rotate(site, monkeypatch):
    old = host_secret(site.app)
    site.app.state.sm.settings.secret_key = CURRENT
    monkeypatch.setenv("SM_SECRET_KEY_PREVIOUS", json.dumps(["another-retired-key", old]))
    return old


async def test_loaded_form_submits_after_rotation_and_checks_its_digest(site, monkeypatch):
    await contact_type(site)
    token = (await load(site))["token"]
    old = rotate(site, monkeypatch)
    stale = sign_form(old, "default", "contact", "0" * 16, now=time.time() - 10)
    response = await send(site, token=stale)
    assert (response.status_code, response.json()["code"]) == (409, "form_changed")
    assert (await send(site, token=token)).status_code == 202
    assert len(await records_of(site)) == 1


async def test_mailed_links_confirm_and_unsubscribe_after_rotation(newsletter, monkeypatch):
    assert (await signup(newsletter)).status_code == 202
    tokens = links_in(newsletter.outbox.sent[-1])
    rotate(newsletter, monkeypatch)
    confirmed = await follow(newsletter, "confirm", tokens["confirm"]["t"])
    assert (confirmed.status_code, confirmed.json()) == (200, {"status": "confirmed"})
    assert (await subscriber(newsletter))["data"]["sm_status"] == "confirmed"
    left = await follow(newsletter, "unsubscribe", tokens["unsubscribe"]["t"])
    assert (left.status_code, left.json()) == (200, {"status": "unsubscribed"})
    assert (await subscriber(newsletter))["data"]["sm_status"] == "unsubscribed"
    assert (await follow(newsletter, "confirm", tokens["confirm"]["t"])).status_code == 410


@pytest.mark.parametrize("action", [links.CONFIRM, links.UNSUBSCRIBE])
async def test_forged_retired_gate_reaches_no_database(newsletter, monkeypatch, action):
    assert (await signup(newsletter)).status_code == 202
    token = links_in(newsletter.outbox.sent[-1])[action]["t"]
    rotate(newsletter, monkeypatch)
    head, _gate, state = token.rsplit(".", 2)
    with statements(newsletter.db_state) as sql:
        response = await follow(newsletter, action, f"{head}.forged.{state}")
    assert not sql
    assert response.status_code == (410 if action == links.CONFIRM else 200)
    assert (await subscriber(newsletter))["data"]["sm_status"] == "pending"


@pytest.mark.parametrize("action", [links.CONFIRM, links.UNSUBSCRIBE])
@pytest.mark.parametrize("retired_gate", [False, True])
async def test_spliced_keys_cannot_change_subscription(
    newsletter, monkeypatch, action, retired_gate
):
    assert (await signup(newsletter)).status_code == 202
    old_token = links_in(newsletter.outbox.sent[-1])[action]["t"]
    row = await subscriber(newsletter)
    rotate(newsletter, monkeypatch)
    # Use identical expiry claims: only the signing key differs.
    exp = int(old_token.rsplit(".", 3)[1]) if action == links.CONFIRM else None
    current_token = links.sign(
        CURRENT,
        action,
        tenant="default",
        type_key=LIST,
        uuid=row["uuid"],
        nonce=row["data"]["sm_nonce"],
        exp=exp,
    )
    gate_token, state_token = (
        (old_token, current_token) if retired_gate else (current_token, old_token)
    )
    spliced = gate_token.rsplit(".", 1)[0] + "." + state_token.rsplit(".", 1)[1]
    response = await follow(newsletter, action, spliced)
    assert response.status_code == (410 if action == links.CONFIRM else 200)
    assert (await subscriber(newsletter))["data"]["sm_status"] == "pending"
