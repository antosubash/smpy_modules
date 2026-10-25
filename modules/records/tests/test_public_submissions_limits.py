"""Website submissions (#101): the rate limits, the links heuristic, and the
cases where a submission is stored and deliberately not mailed."""

from __future__ import annotations

import logging

from sm_records.contracts.events import FormSubmitted

from tests.submissions_http import (
    configure,
    contact_type,
    host_parts,
    load,
    records_of,
    send,
)

SPAMMY = {
    "name": "Bot",
    "email": "bot@example.org",
    "message": "http://a.example www.b.example https://c.example http://d.example",
}


async def test_the_sixth_submission_from_one_address_is_429(site):
    await contact_type(site)
    token = (await load(site))["token"]
    for _ in range(5):
        assert (await send(site, token=token)).status_code == 202
    over = await send(site, token=token)
    assert over.status_code == 429, over.text
    assert over.json()["code"] == "rate_limited"
    assert int(over.headers["retry-after"]) > 0
    assert len(await records_of(site)) == 5


async def test_one_type_is_throttled_across_addresses(site):
    configure(site, public_submissions_rate_per_ip="off", public_submissions_type_rate="2/hour")
    await contact_type(site)
    await contact_type(site, "other")
    for _ in range(2):
        assert (await send(site)).status_code == 202
    assert (await send(site)).status_code == 429
    assert (await send(site, "other")).status_code == 202, "another type has its own budget"


async def test_a_message_full_of_links_is_kept_as_spam(site):
    seen: list = []

    async def note(event):
        seen.append(event)

    site.app.state.sm.event_bus.subscribe(FormSubmitted, note)
    configure(site, public_submissions_max_links=3)
    await contact_type(site)
    resp = await send(site, data=SPAMMY)
    assert (resp.status_code, resp.json()) == (202, {"ok": True}), "the bot cannot tell"
    assert await records_of(site) == []
    (trashed,) = await records_of(site, trashed=True)
    assert trashed["data"]["sm_spam"] == "links"
    assert trashed["data"]["sm_notified_at"] is None
    assert site.outbox.sent == []
    assert seen[0].spam is True


async def test_the_links_check_can_be_turned_off(site):
    configure(site, public_submissions_max_links=0)
    await contact_type(site)
    assert (await send(site, data=SPAMMY)).status_code == 202
    (record,) = await records_of(site)
    assert record["data"]["sm_spam"] is None
    assert len(site.outbox.sent) == 1


async def test_a_type_that_notifies_nobody_stores_and_sends_nothing(site):
    await contact_type(site, notify_to=[])
    assert (await send(site)).status_code == 202
    (record,) = await records_of(site)
    assert record["data"]["sm_notified_at"] is None
    assert site.outbox.sent == []


async def test_without_a_public_base_url_nothing_is_mailed(site, caplog):
    host_parts(site.app, base_url="")
    await contact_type(site)
    with caplog.at_level(logging.WARNING, logger="sm_records.public_submissions.mail_runner"):
        assert (await send(site)).status_code == 202
    (record,) = await records_of(site)
    assert record["data"]["sm_notified_at"] is None
    assert site.outbox.sent == []
    assert "public_base_url" in caplog.text


async def test_a_sender_that_only_logs_leaves_it_not_sent(site, caplog):
    site.outbox.delivers_email = False
    await contact_type(site)
    with caplog.at_level(logging.WARNING, logger="sm_records.public_submissions.mail_runner"):
        assert (await send(site)).status_code == 202
    (record,) = await records_of(site)
    assert record["data"]["sm_notified_at"] is None
    assert "delivers email" in caplog.text


async def test_every_recipient_gets_one_message(site):
    await contact_type(site, notify_to=["a@example.org", "B@example.org", "b@example.org"])
    assert (await send(site)).status_code == 202
    assert [m.to for m in site.outbox.sent] == ["a@example.org", "B@example.org"], (
        "recipients are de-duplicated case-insensitively"
    )


async def test_the_ip_hash_and_user_agent_can_be_left_out(site):
    configure(
        site,
        public_submissions_store_ip_hash=False,
        public_submissions_store_user_agent=False,
    )
    await contact_type(site)
    assert (await send(site, headers={"User-Agent": "Browser/1.0"})).status_code == 202
    (record,) = await records_of(site)
    assert record["data"]["sm_ip_hash"] is None
    assert record["data"]["sm_user_agent"] is None
