"""The system fields a public-submissions type carries (#101): injected on
every save, never taken from the client, re-injected by a rollback, and the
``sm_`` prefix reserved for them."""

from __future__ import annotations

from tests.app_harness import ADMIN, api_record, field, roles, seed_type
from tests.public_submissions_support import (
    API,
    FORM_SYSTEM_KEYS,
    contact_fields,
    create,
    keys_of,
    system_keys,
    update,
)


async def test_create_appends_the_kinds_system_fields(client):
    resp = await create(client)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert keys_of(body) == ["name", "email", "message", "triage", *FORM_SYSTEM_KEYS]
    assert all(entry["system"] == "readonly" for entry in body["fields"][4:])
    assert all("system" not in entry for entry in body["fields"][:4])
    assert body["public_submissions"] == {
        "kind": "form",
        "enabled": False,
        "public_fields": ["name", "email", "message"],
        "notify_to": [],
        "consent": {"required": False, "text": {}},
        "double_opt_in": True,
        "retention_days": 365,
        "pending_purge_days": 30,
    }


async def test_client_sent_system_entries_are_replaced(client):
    fields = contact_fields()
    forged = field("sm_source_page", indexed=False)
    forged.update(system="readonly", label="Mine now", required=True)
    evil = field("sm_evil", indexed=False)
    evil["system"] = "readonly"
    resp = await create(client, fields=[*fields, forged, evil])
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert system_keys(body) == FORM_SYSTEM_KEYS
    source = next(e for e in body["fields"] if e["key"] == "sm_source_page")
    assert source["label"] == "Source page"
    assert source["required"] is False


async def test_an_ordinary_type_drops_system_entries_too(client):
    forged = field("sm_spam", indexed=False)
    forged["system"] = "readonly"
    resp = await client.post(
        API,
        json={"key": "plain", "label": "Plain", "fields": [field("title"), forged]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    assert keys_of(resp.json()) == ["title"]


async def test_the_sm_prefix_is_refused_on_save(client):
    resp = await client.post(
        API,
        json={"key": "plain", "label": "Plain", "fields": [field("sm_mine")]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == "sm_mine"
    assert "reserved for system fields" in resp.json()["errors"][0]["message"]


async def test_a_stored_sm_key_still_loads(client, records_app):
    _, db_state = records_app
    await seed_type(db_state, "legacy", [field("sm_mine")])
    record = await api_record(client, "legacy", {"sm_mine": "kept"})
    assert record["data"]["sm_mine"] == "kept"
    listed = await client.get(f"{API}/legacy/records", headers=roles(ADMIN))
    assert listed.status_code == 200


async def test_resending_the_fields_is_a_no_op(client):
    created = (await create(client)).json()
    resp = await update(client, "contact", fields=created["fields"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["schema_version"] == created["schema_version"]
    # Without the system entries they come back all the same.
    resp = await update(client, "contact", fields=created["fields"][:4])
    assert resp.json()["schema_version"] == created["schema_version"]
    assert system_keys(resp.json()) == FORM_SYSTEM_KEYS


async def test_a_legacy_types_resave_is_still_a_no_op(client):
    created = (
        await client.post(
            API,
            json={"key": "plain", "label": "Plain", "fields": [field("title")]},
            headers=roles(ADMIN),
        )
    ).json()
    assert all("system" not in entry for entry in created["fields"])
    resp = await update(client, "plain", fields=created["fields"])
    assert resp.json()["schema_version"] == created["schema_version"]


async def test_the_first_kind_on_a_populated_type_is_an_additive_change(client):
    await client.post(
        API,
        json={"key": "contact", "label": "Contact", "fields": contact_fields()},
        headers=roles(ADMIN),
    )
    record = await api_record(client, "contact", {"name": "A", "email": "a@x.io", "message": "hi"})
    before = (await client.get(f"{API}/contact", headers=roles(ADMIN))).json()
    resp = await update(client, "contact", public_submissions={"kind": "form"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert system_keys(body) == FORM_SYSTEM_KEYS
    assert body["schema_version"] == before["schema_version"] + 1
    read = await client.get(f"{API}/contact/records/{record['uuid']}", headers=roles(ADMIN))
    assert read.json()["invalid"] == []


async def test_a_rollback_keeps_the_system_fields(client):
    await client.post(
        API,
        json={"key": "contact", "label": "Contact", "fields": contact_fields()},
        headers=roles(ADMIN),
    )
    first = (await client.get(f"{API}/contact", headers=roles(ADMIN))).json()
    updated = (await update(client, "contact", public_submissions={"kind": "form"})).json()
    resp = await client.post(
        f"{API}/contact/revisions/{first['version']}/restore",
        json={"expected_version": updated["version"]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    assert system_keys(resp.json()) == FORM_SYSTEM_KEYS


async def test_a_newsletter_type_is_keyed_by_its_address(client):
    resp = await create(client, "newsletter", fields=[], config={"kind": "subscription"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["display_field"] == "sm_email"
    email = next(e for e in body["fields"] if e["key"] == "sm_email")
    assert (email["required"], email["unique"], email["indexed"]) == (True, True, True)
    nonce = next(e for e in body["fields"] if e["key"] == "sm_nonce")
    assert nonce["system"] == "internal"


async def test_an_empty_type_made_a_newsletter_is_keyed_by_its_address(client):
    await client.post(
        API, json={"key": "list", "label": "List", "fields": []}, headers=roles(ADMIN)
    )
    resp = await update(client, "list", public_submissions={"kind": "subscription"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["display_field"] == "sm_email"


async def test_a_populated_type_cannot_become_a_newsletter(client):
    await client.post(
        API,
        json={"key": "list", "label": "List", "fields": [field("title")]},
        headers=roles(ADMIN),
    )
    await api_record(client, "list", {"title": "x"})
    resp = await update(client, "list", public_submissions={"kind": "subscription"})
    assert resp.status_code == 409
    assert "no records" in resp.json()["detail"]


async def test_system_fields_count_against_the_indexed_ceiling(client):
    fields = [field(f"f{i}") for i in range(24)]
    assert (await create(client, "ok", fields=fields, config={"kind": "form"})).status_code == 201
    resp = await create(client, "full", fields=fields, config={"kind": "subscription"})
    assert resp.status_code == 422
    assert "indexed fields exceeds" in resp.json()["detail"]
