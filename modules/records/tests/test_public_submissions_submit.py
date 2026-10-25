"""Website submissions, end to end over HTTP (#101): the definition, the happy
path, and every refusal before the write."""

from __future__ import annotations

import time

from sm_records.contracts.events import FormSubmitted, RecordCreated
from sm_records.public_submissions.tokens import sign_form

from tests.app_harness import ADMIN, roles
from tests.public_submissions_support import form_config, update
from tests.submissions_http import (
    JSON,
    SUBMISSIONS,
    configure,
    contact_type,
    load,
    records_of,
    send,
)

SECRET = "submissions-test-secret"


async def test_the_definition_lists_the_public_fields_only(site):
    await contact_type(
        site, consent={"required": True, "text": {"en": "OK?", "de": "Einverstanden?"}}
    )
    resp = await site.get(f"{SUBMISSIONS}/contact?locale=de")
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert body["kind"] == "form"
    assert [f["key"] for f in body["fields"]] == ["name", "email", "message"]
    assert body["fields"][1]["type"] == "email" and body["fields"][0]["required"] is True
    assert body["consent"] == {"required": True, "text": "Einverstanden?"}
    assert len(body["token"].split(".")) == 4
    assert body["captcha"] is None


async def test_a_submission_is_stored_as_a_draft_and_mailed(site):
    seen: list = []

    async def note(event):
        seen.append(event)

    for event_type in (RecordCreated, FormSubmitted):
        site.app.state.sm.event_bus.subscribe(event_type, note)
    await contact_type(site)
    resp = await send(
        site,
        headers={"Referer": "http://test/p/contact?x=1", "User-Agent": "Browser/1.0"},
        block="block-1",
        locale="DE",
    )
    assert (resp.status_code, resp.json()) == (202, {"ok": True})
    assert resp.headers["cache-control"] == "no-store"
    (record,) = await records_of(site)
    assert record["status"] == "draft"
    data = record["data"]
    assert data["email"] == "ada@example.org", "trimmed and lowercased"
    assert data["triage"] == "new", "a non-public field gets its default"
    assert data["sm_source_page"] == "/p/contact"
    assert data["sm_source_block"] == "block-1"
    assert data["sm_locale"] == "de"
    assert len(data["sm_ip_hash"]) == 64
    assert data["sm_user_agent"] == "Browser/1.0"
    assert data["sm_spam"] is None and data["sm_consent_text"] is None
    assert data["sm_notified_at"], "the delivery mark is written after the send"
    (message,) = site.outbox.sent
    assert message.to == "ops@example.org"
    assert message.subject == "New Contact submission on site.example"
    assert "Name: Ada" in message.text and "Message: Hello" in message.text
    assert f"https://site.example/admin/records/contact/{record['uuid']}" in message.text
    assert [type(e) for e in seen] == [RecordCreated, FormSubmitted]
    assert seen[1].uuid == record["uuid"] and seen[1].spam is False


async def test_the_delivery_mark_is_not_announced_as_an_edit(site):
    """The mark is a system write inside ``events.muted``, and one revision."""
    from sm_records.contracts.events import RecordUpdated

    updates: list = []

    async def note(event):
        updates.append(event)

    site.app.state.sm.event_bus.subscribe(RecordUpdated, note)
    await contact_type(site)
    await send(site)
    assert updates == []


async def test_a_honeypot_hit_is_accepted_and_dropped(site):
    await contact_type(site)
    for trap in ("I am a bot", "x" * 5000):
        resp = await send(site, hp=trap)
        assert (resp.status_code, resp.json()) == (202, {"ok": True}), "any value, same answer"
    assert await records_of(site) == []
    assert site.outbox.sent == []


async def test_a_foreign_origin_is_refused(site):
    await contact_type(site)
    token = (await load(site))["token"]
    for headers in ({"Origin": "https://evil.example"}, {"Origin": "null"}):
        resp = await send(site, token=token, headers=headers)
        assert resp.status_code == 403, resp.text
        assert resp.json()["code"] == "bad_origin"
    assert await records_of(site) == []


async def test_a_listed_origin_and_the_base_url_are_accepted(site):
    configure(site, public_submissions_allowed_origins=("https://www.example.org/",))
    await contact_type(site)
    for origin in ("https://www.example.org", "https://site.example"):
        assert (await send(site, headers={"Origin": origin})).status_code == 202


async def test_the_referer_stands_in_for_a_missing_origin(site):
    await contact_type(site)
    token = (await load(site))["token"]
    payload = {"data": {"name": "A", "email": "a@b.org", "message": "m"}, "token": token}
    url = f"{SUBMISSIONS}/contact/submit"
    plain = {"Content-Type": "application/json"}
    assert (await site.post(url, json=payload, headers=plain)).json()["code"] == "bad_origin"
    ok = await site.post(url, json=payload, headers={**plain, "Referer": "http://test/p/x"})
    assert ok.status_code == 202, ok.text


async def test_a_body_that_is_not_json_is_refused(site):
    await contact_type(site)
    resp = await site.post(
        f"{SUBMISSIONS}/contact/submit",
        content=b"data=x",
        headers={"Origin": "http://test", "Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 415, resp.text
    assert resp.json()["code"] == "unsupported_media_type"


async def test_an_oversized_body_is_refused_before_it_is_read(site):
    await contact_type(site)
    resp = await site.post(
        f"{SUBMISSIONS}/contact/submit", content=b"{" + b" " * 20000 + b"}", headers=JSON
    )
    assert resp.status_code == 413, resp.text
    assert resp.headers["cache-control"] == "no-store"


async def test_a_bad_young_or_old_token_is_form_expired(site):
    await contact_type(site)
    digest = "0" * 16
    old = sign_form(SECRET, "default", "contact", digest, now=time.time() - 8000)
    other_type = sign_form(SECRET, "default", "other", digest)
    for token in ("garbage", old, other_type, ""):
        resp = await send(site, token=token)
        assert resp.status_code == 400, (token, resp.text)
        assert resp.json()["code"] == "form_expired"
    configure(site, public_submissions_min_fill_seconds=60)
    resp = await send(site)
    assert (resp.status_code, resp.json()["code"]) == (400, "form_expired")
    assert await records_of(site) == []


async def test_a_form_loaded_before_a_schema_change_is_form_changed(site):
    rtype = await contact_type(site)
    token = (await load(site))["token"]
    fields = [*rtype["fields"], {"key": "phone", "type": "text", "label": "Phone"}]
    changed = await update(site, "contact", fields=[f for f in fields if not f.get("system")])
    assert changed.status_code == 200, changed.text
    resp = await send(site, token=token)
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["code"] == "form_changed"
    assert body["definition"]["schema_version"] == changed.json()["schema_version"]
    assert (await send(site, token=body["definition"]["token"])).status_code == 202


async def test_the_fresh_form_after_form_changed_can_be_sent_at_once(site):
    """The visitor already spent the fill time on the old form."""
    configure(site, public_submissions_min_fill_seconds=3)
    await contact_type(site)
    stale = sign_form(SECRET, "default", "contact", "0" * 16, now=time.time() - 10)
    changed = await send(site, token=stale)
    assert changed.json()["code"] == "form_changed"
    assert (await send(site, token=changed.json()["definition"]["token"])).status_code == 202


async def test_an_odd_honeypot_or_deeply_nested_value_is_no_500(site):
    await contact_type(site)
    for odd in (0, [], {"x": 1}):
        assert (await send(site, hp=odd)).status_code == 202
    assert await records_of(site) == [], "a non-string value in the trap is a bot, whatever it is"
    deep: object = "http://x.example"
    for _ in range(2000):
        deep = [deep]
    resp = await send(site, data={"name": "A", "email": "a@b.org", "message": deep})
    assert resp.status_code == 422, resp.text


async def test_a_reworded_consent_text_is_form_changed(site):
    """The consent text bumps no schema version, yet a visitor who ticked the
    box agreed to the words they saw — not to the new ones."""
    await contact_type(site, consent={"required": True, "text": {"en": "Old words."}})
    token = (await load(site))["token"]
    reworded = await update(
        site,
        "contact",
        public_submissions=form_config(
            enabled=True,
            notify_to=["ops@example.org"],
            consent={"required": True, "text": {"en": "New words."}},
        ),
    )
    assert reworded.status_code == 200, reworded.text
    resp = await send(site, token=token, consent=True)
    assert (resp.status_code, resp.json()["code"]) == (409, "form_changed")
    assert resp.json()["definition"]["consent"]["text"] == "New words."
    assert await records_of(site) == []
    fresh = resp.json()["definition"]["token"]
    assert (await send(site, token=fresh, consent=True)).status_code == 202
    (record,) = await records_of(site)
    assert record["data"]["sm_consent_text"] == "New words."


async def test_a_field_outside_the_allowlist_is_refused(site):
    await contact_type(site)
    resp = await send(
        site, data={"name": "A", "email": "a@b.org", "message": "m", "triage": "done"}
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["code"] == "unknown_field"
    assert [e["field"] for e in resp.json()["errors"]] == ["triage"]
    system = await send(
        site, data={"name": "A", "email": "a@b.org", "message": "m", "sm_spam": None}
    )
    assert system.json()["code"] == "unknown_field", "a visitor cannot write a system value"


async def test_invalid_data_is_a_per_field_422(site):
    await contact_type(site)
    resp = await send(site, data={"email": "not an email", "message": "m"})
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["code"] == "invalid"
    assert {e["field"] for e in body["errors"]} >= {"name", "email"}


async def test_required_consent_is_checked_and_snapshotted(site):
    await contact_type(site, consent={"required": True, "text": {"en": "I agree."}})
    refused = await send(site)
    assert (refused.status_code, refused.json()["code"]) == (422, "consent_required")
    assert (await send(site, consent=True, locale="fr")).status_code == 202
    (record,) = await records_of(site)
    assert record["data"]["sm_consent_text"] == "I agree.", "falls back to the default locale"


async def test_every_closed_door_is_the_same_404(site):
    await contact_type(site)
    await contact_type(site, "closed", enabled=False)
    plain = await site.post(
        "/api/records/types",
        json={"key": "plain", "label": "P", "fields": []},
        headers=roles(ADMIN),
    )
    assert plain.status_code == 201, plain.text
    news = await site.post(
        "/api/records/types",
        json={
            "key": "news",
            "label": "N",
            "fields": [],
            "public_submissions": {"kind": "subscription", "enabled": True},
        },
        headers=roles(ADMIN),
    )
    assert news.status_code == 201, news.text
    unknown = await site.get(f"{SUBMISSIONS}/nosuch")
    assert unknown.status_code == 404
    for key in ("closed", "plain", "news"):
        resp = await site.get(f"{SUBMISSIONS}/{key}")
        assert (resp.status_code, resp.json()) == (404, unknown.json()), key
        posted = await send(site, key, token="x")
        assert posted.status_code in (400, 404), key
    configure(site, public_submissions_enabled=False)
    resp = await site.get(f"{SUBMISSIONS}/contact")
    assert (resp.status_code, resp.json()) == (404, unknown.json())
    assert (await send(site, token="x")).status_code == 404
