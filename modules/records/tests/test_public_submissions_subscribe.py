"""A newsletter signup over HTTP (#101, design §7.1): the definition, the state
machine, the per-address budget, and answers that say nothing about the list."""

from __future__ import annotations

import asyncio

import pytest
from sm_records.contracts.events import RecordCreated, SubscriptionChanged
from sm_records.public_submissions import mail_runner

from tests.app_harness import ADMIN, roles
from tests.newsletter_http import (
    ADDRESS,
    LIST,
    STORED,
    admin,
    follow,
    links_in,
    newsletter_type,
    records_of,
    signup,
    subscriber,
)
from tests.pg_support import USING_POSTGRES
from tests.submissions_http import SUBMISSIONS, configure


def _events(site, *types):
    seen: list = []

    async def note(event):
        seen.append(event)

    for event_type in types:
        site.app.state.sm.event_bus.subscribe(event_type, note)
    return seen


async def test_the_definition_asks_for_the_address_first(newsletter):
    body = (await newsletter.get(f"{SUBMISSIONS}/{LIST}")).json()
    assert body["kind"] == "subscription"
    assert [f["key"] for f in body["fields"]] == ["sm_email", "first_name"]
    assert body["fields"][0]["type"] == "email" and body["fields"][0]["required"] is True


async def test_a_signup_is_pending_and_mailed_a_confirmation(newsletter):
    seen = _events(newsletter, RecordCreated, SubscriptionChanged)
    resp = await signup(newsletter, data={"first_name": "Ada"}, locale="de")
    assert (resp.status_code, resp.json()) == (202, {"ok": True})
    assert resp.headers["cache-control"] == "no-store"
    record = await subscriber(newsletter)
    data = record["data"]
    assert record["status"] == "draft"
    assert data["sm_email"] == STORED and data["first_name"] == "Ada"
    assert data["sm_status"] == "pending" and data["sm_locale"] == "de"
    assert data["sm_consent_at"] and len(data["sm_consent_ip_hash"]) == 64
    assert len(data["sm_nonce"]) == 32 and data["sm_confirmed_at"] is None
    assert data["sm_confirm_sent_at"], "the mark is written once the mail is out"
    (message,) = newsletter.outbox.sent
    assert message.to == STORED
    assert "Abonnement" in message.subject, "in the subscriber's language"
    found = links_in(message)
    assert set(found) == {"confirm", "unsubscribe"}
    assert found["confirm"]["l"] == "de"
    assert data["sm_nonce"] not in message.text and "secret" not in message.text
    assert [type(e) for e in seen] == [RecordCreated, SubscriptionChanged]
    assert (seen[1].status_before, seen[1].status_after) == (None, "pending")


async def test_every_state_answers_the_same(newsletter):
    """New, pending, confirmed, unsubscribed and trashed: one answer."""
    answers = [await signup(newsletter)]
    answers.append(await signup(newsletter))  # pending
    confirm = links_in(newsletter.outbox.sent[0])["confirm"]["t"]
    assert (await follow(newsletter, "confirm", confirm)).json()["status"] == "confirmed"
    answers.append(await signup(newsletter))  # confirmed
    record = await subscriber(newsletter)
    assert (await admin(newsletter, record["uuid"], "unsubscribe")).status_code == 200
    answers.append(await signup(newsletter))  # unsubscribed
    uuid = (await subscriber(newsletter))["uuid"]
    deleted = await newsletter.delete(
        f"/api/records/types/{LIST}/records/{uuid}", headers=roles(ADMIN)
    )
    assert deleted.status_code in (200, 204), deleted.text
    answers.append(await signup(newsletter))  # trashed
    shapes = {(r.status_code, r.text, r.headers.get("cache-control")) for r in answers}
    assert shapes == {(202, '{"ok":true}', "no-store")}
    assert len(await records_of(newsletter)) == 1, "one record per address, restored"


async def test_a_refusal_is_the_same_whether_the_address_is_on_the_list(newsletter):
    long_name = {"first_name": "x" * 5000}
    fresh = await signup(newsletter, "new@example.org", data=long_name)
    await signup(newsletter)
    listed = await signup(newsletter, data=long_name)
    assert fresh.status_code == listed.status_code == 422
    assert fresh.json()["code"] == listed.json()["code"] == "invalid"
    bad = await signup(newsletter, "not an address")
    assert (bad.status_code, bad.json()["code"]) == (422, "invalid")


async def test_a_confirmed_subscriber_is_never_mailed_by_a_signup(newsletter):
    await signup(newsletter)
    confirm = links_in(newsletter.outbox.sent[0])["confirm"]["t"]
    await follow(newsletter, "confirm", confirm)
    before = len(newsletter.outbox.sent)
    for _ in range(3):
        assert (await signup(newsletter)).status_code == 202
    assert len(newsletter.outbox.sent) == before
    assert (await subscriber(newsletter))["data"]["sm_status"] == "confirmed"


async def test_a_pending_signup_is_mailed_again_within_its_budget(newsletter):
    """``3/day`` per address: the fourth signup still answers 202, unsent."""
    for _ in range(4):
        assert (await signup(newsletter)).status_code == 202
    assert len(newsletter.outbox.sent) == 3
    assert len(await records_of(newsletter)) == 1
    other = await signup(newsletter, "other@example.org")
    assert other.status_code == 202 and len(newsletter.outbox.sent) == 4, "per address"


async def test_a_resubscribe_rotates_the_nonce_and_kills_old_links(newsletter):
    await signup(newsletter)
    old = links_in(newsletter.outbox.sent[0])
    before = (await subscriber(newsletter))["data"]["sm_nonce"]
    await follow(newsletter, "unsubscribe", old["unsubscribe"]["t"])
    seen = _events(newsletter, SubscriptionChanged)
    await signup(newsletter)
    data = (await subscriber(newsletter))["data"]
    assert data["sm_status"] == "pending" and data["sm_nonce"] != before
    assert data["sm_consent_at"] and data["sm_unsubscribed_at"] is None
    assert [(e.status_before, e.status_after) for e in seen] == [("unsubscribed", "pending")]
    assert (await follow(newsletter, "confirm", old["confirm"]["t"])).status_code == 410
    await follow(newsletter, "unsubscribe", old["unsubscribe"]["t"])
    assert (await subscriber(newsletter))["data"]["sm_status"] == "pending", "dead link"
    fresh = links_in(newsletter.outbox.sent[-1])["confirm"]["t"]
    assert (await follow(newsletter, "confirm", fresh)).json()["status"] == "confirmed"


async def test_a_trashed_subscriber_is_restored_as_pending(newsletter):
    await signup(newsletter)
    uuid = (await subscriber(newsletter))["uuid"]
    await newsletter.delete(f"/api/records/types/{LIST}/records/{uuid}", headers=roles(ADMIN))
    assert await records_of(newsletter) == []
    assert (await signup(newsletter)).status_code == 202
    record = await subscriber(newsletter)
    assert record["uuid"] == uuid and record["data"]["sm_status"] == "pending"


async def test_without_double_opt_in_a_signup_is_confirmed_and_unmailed(site):
    consent = {"required": True, "text": {"en": "Yes, send me news."}}
    await newsletter_type(site, double_opt_in=False, consent=consent)
    refused = await signup(site)
    assert (refused.status_code, refused.json()["code"]) == (422, "consent_required")
    assert (await signup(site, consent=True)).status_code == 202
    data = (await subscriber(site))["data"]
    assert data["sm_status"] == "confirmed" and data["sm_confirmed_at"]
    assert data["sm_consent_text"] == "Yes, send me news."
    assert site.outbox.sent == []


@pytest.mark.skipif(not USING_POSTGRES, reason="the type lock serialises on Postgres only")
async def test_two_signups_of_one_address_at_once_make_one_record(newsletter):
    """The loser of ``unique``'s check under the type lock is the same 202."""
    first, second = await asyncio.gather(signup(newsletter), signup(newsletter))
    assert first.status_code == second.status_code == 202
    await mail_runner.drain()
    (record,) = await records_of(newsletter)
    assert record["data"]["sm_email"] == STORED


async def test_the_honeypot_and_a_closed_list_store_nothing(newsletter):
    assert (await signup(newsletter, hp="bot")).status_code == 202
    assert await records_of(newsletter) == [] and newsletter.outbox.sent == []
    configure(newsletter, public_submissions_enabled=False)
    assert (await newsletter.get(f"{SUBMISSIONS}/{LIST}")).status_code == 404


async def test_an_address_is_one_inbox_whatever_its_spelling(newsletter):
    await signup(newsletter, ADDRESS)
    await signup(newsletter, "  READER@example.ORG")
    assert len(await records_of(newsletter)) == 1
