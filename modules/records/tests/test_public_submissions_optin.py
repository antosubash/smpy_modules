"""Confirming and leaving a newsletter list (#101, design §4.2, §4.4, §7.2): the
link routes, their replay and expiry, the landing pages and the admin actions."""

from __future__ import annotations

import time

from sm_records.contracts.events import SubscriptionChanged
from sm_records.public_submissions import links, mail_runner
from sm_records.public_submissions.tokens import host_secret

from tests.app_harness import ADMIN, roles
from tests.newsletter_http import (
    LIST,
    admin,
    follow,
    links_in,
    records_of,
    signup,
    subscriber,
)
from tests.submissions_http import configure, contact_type

INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


async def _signed_up(site) -> dict[str, str]:
    assert (await signup(site)).status_code == 202
    found = links_in(site.outbox.sent[-1])
    return {action: found[action]["t"] for action in found}


async def test_the_link_confirms_by_post_and_a_replay_changes_nothing(newsletter):
    seen: list = []

    async def note(event):
        seen.append(event)

    newsletter.app.state.sm.event_bus.subscribe(SubscriptionChanged, note)
    tokens = await _signed_up(newsletter)
    page = await newsletter.get(
        f"/records/submissions/confirm?t={tokens['confirm']}", headers=INERTIA
    )
    assert page.status_code == 200, page.text
    assert (await subscriber(newsletter))["data"]["sm_status"] == "pending", "GET changes nothing"
    first = await follow(newsletter, "confirm", tokens["confirm"])
    assert (first.status_code, first.json()) == (200, {"status": "confirmed"})
    assert first.headers["cache-control"] == "no-store"
    data = (await subscriber(newsletter))["data"]
    assert data["sm_status"] == "confirmed" and data["sm_confirmed_at"]
    again = await follow(newsletter, "confirm", tokens["confirm"])
    assert again.json() == {"status": "already_confirmed"}
    assert [(e.status_before, e.status_after) for e in seen[-1:]] == [("pending", "confirmed")]


async def test_a_form_encoded_body_is_accepted(newsletter):
    tokens = await _signed_up(newsletter)
    resp = await follow(newsletter, "confirm", tokens["confirm"], form=True)
    assert resp.json() == {"status": "confirmed"}
    resp = await follow(newsletter, "unsubscribe", tokens["unsubscribe"], form=True)
    assert resp.json() == {"status": "unsubscribed"}
    assert (await subscriber(newsletter))["data"]["sm_status"] == "unsubscribed"


async def test_an_expired_or_forged_confirm_link_is_gone(newsletter):
    tokens = await _signed_up(newsletter)
    record = await subscriber(newsletter)
    secret = host_secret(newsletter.app)
    claims = {"tenant": "default", "type_key": LIST, "uuid": record["uuid"]}
    nonce = record["data"]["sm_nonce"]
    expired = links.sign(secret, links.CONFIRM, nonce=nonce, exp=int(time.time()) - 1, **claims)
    other_nonce = links.sign(
        secret, links.CONFIRM, nonce="0" * 32, exp=int(time.time()) + 60, **claims
    )
    forged = tokens["confirm"][:-2] + ("AA" if not tokens["confirm"].endswith("AA") else "BB")
    for token in (expired, other_nonce, forged, "", "x" * 1000, 7, None):
        resp = await follow(newsletter, "confirm", token)
        assert (resp.status_code, resp.json()["code"]) == (410, "link_expired"), token
    assert (await subscriber(newsletter))["data"]["sm_status"] == "pending"


async def test_unsubscribe_answers_the_same_whatever_the_link(newsletter):
    tokens = await _signed_up(newsletter)
    answers = [await follow(newsletter, "unsubscribe", tokens["unsubscribe"])]
    data = (await subscriber(newsletter))["data"]
    assert data["sm_status"] == "unsubscribed" and data["sm_unsubscribed_at"]
    assert data["sm_email"], "kept as the suppression record"
    assert data["sm_consent_text"] is data["sm_consent_at"] is data["sm_consent_ip_hash"] is None
    assert data.get("first_name") is None
    answers.append(await follow(newsletter, "unsubscribe", tokens["unsubscribe"]))
    answers.append(await follow(newsletter, "unsubscribe", "default.news.nobody.AAAA.BBBB"))
    answers.append(await follow(newsletter, "unsubscribe", "garbage"))
    answers.append(await newsletter.post("/api/records/submissions/unsubscribe", content=b"x"))
    assert {(r.status_code, r.text) for r in answers} == {(200, '{"status":"unsubscribed"}')}
    assert (await follow(newsletter, "confirm", tokens["confirm"])).status_code == 410


async def test_the_landing_page_speaks_the_links_language_and_is_never_cached(newsletter):
    page = await newsletter.get("/records/submissions/unsubscribe?t=anything&l=de", headers=INERTIA)
    assert page.status_code == 200, page.text
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["referrer-policy"] == "no-referrer"
    body = page.json()
    assert body["component"] == "Records/SubmissionAction"
    props = body["props"]
    assert props["action"] == "unsubscribe" and props["token"] == "anything"
    assert props["locale"] == "de" and props["copy"]["button"] == "Abmelden"
    assert props["endpoint"] == "/api/records/submissions/unsubscribe"
    unknown = await newsletter.get("/records/submissions/confirm?l=xx-yy", headers=INERTIA)
    assert unknown.json()["props"]["locale"] == "en"
    html = await newsletter.get("/records/submissions/confirm?t=x&l=de")
    assert html.headers["content-language"] == "de"


def test_the_shells_html_lang_is_rewritten():
    from fastapi import Response
    from sm_records._html_lang import set_html_lang

    response = set_html_lang(Response(b'<html lang="en"><body lang="x">'), "de")
    assert response.body == b'<html lang="de" data-shell-lang="en"><body lang="x">'


async def test_the_master_switch_closes_the_links_too(newsletter):
    tokens = await _signed_up(newsletter)
    configure(newsletter, public_submissions_enabled=False)
    assert (await follow(newsletter, "confirm", tokens["confirm"])).status_code == 404
    # ...but not the way out: a mail already sent must keep its unsubscribe link.
    leave = await follow(newsletter, "unsubscribe", tokens["unsubscribe"])
    assert (leave.status_code, leave.json()) == (200, {"status": "unsubscribed"})


async def test_a_disabled_list_does_not_confirm_but_still_unsubscribes(newsletter):
    tokens = await _signed_up(newsletter)
    current = (await newsletter.get(f"/api/records/types/{LIST}", headers=roles(ADMIN))).json()
    config = {**current["public_submissions"], "enabled": False}
    updated = await newsletter.put(
        f"/api/records/types/{LIST}",
        json={"expected_version": current["version"], "public_submissions": config},
        headers=roles(ADMIN),
    )
    assert updated.status_code == 200, updated.text
    assert (await follow(newsletter, "confirm", tokens["confirm"])).status_code == 410
    await follow(newsletter, "unsubscribe", tokens["unsubscribe"])
    assert (await subscriber(newsletter))["data"]["sm_status"] == "unsubscribed"


async def test_admin_resend_and_unsubscribe(newsletter):
    await _signed_up(newsletter)
    uuid = (await subscriber(newsletter))["uuid"]
    resent = await admin(newsletter, uuid, "resend")
    assert resent.status_code == 202, resent.text
    await mail_runner.drain()
    assert len(newsletter.outbox.sent) == 2
    await admin(newsletter, uuid, "resend")
    limited = await admin(newsletter, uuid, "resend")
    assert (limited.status_code, limited.json()["code"]) == (429, "rate_limited")
    gone = await admin(newsletter, uuid, "unsubscribe")
    assert gone.status_code == 200, gone.text
    assert gone.json()["data"]["sm_status"] == "unsubscribed"
    assert (await admin(newsletter, uuid, "unsubscribe")).status_code == 200, "idempotent"
    not_pending = await admin(newsletter, uuid, "resend")
    assert (not_pending.status_code, not_pending.json()["code"]) == (409, "not_pending")
    old = links_in(newsletter.outbox.sent[0])["confirm"]["t"]
    assert (await follow(newsletter, "confirm", old)).status_code == 410, "nonce rotated"


async def test_unsubscribe_and_spam_refuse_the_other_kind(newsletter):
    await contact_type(newsletter)
    from tests.submissions_http import records_of as contact_records
    from tests.submissions_http import send

    await send(newsletter)
    (submission,) = await contact_records(newsletter)
    wrong = await admin(newsletter, submission["uuid"], "unsubscribe", key="contact")
    assert (wrong.status_code, wrong.json()["code"]) == (409, "wrong_kind")
    await _signed_up(newsletter)
    (record,) = await records_of(newsletter)
    spam = await admin(newsletter, record["uuid"], "spam")
    assert (spam.status_code, spam.json()["code"]) == (409, "wrong_kind")
