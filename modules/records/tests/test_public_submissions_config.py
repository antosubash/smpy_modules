"""The rules a ``public_submissions`` config obeys on save (#101, design §3.3)."""

from __future__ import annotations

import pytest

from tests.app_harness import ADMIN, field, roles
from tests.public_submissions_support import (
    API,
    contact_fields,
    create,
    form_config,
    update,
)


def _message(resp) -> str:
    body = resp.json()
    return body.get("detail") or body["errors"][0]["message"]


@pytest.mark.parametrize(
    ("config", "needle"),
    [
        ({"kind": "poll"}, "kind"),
        (form_config(surprise=True), "surprise"),
        (form_config(notify_to=["not-an-address"]), "notify_to"),
        (form_config(notify_to=[f"a{i}@x.io" for i in range(11)]), "notify_to"),
        (form_config(retention_days=-1), "retention_days"),
        (form_config(retention_days=36501), "retention_days"),
        ({"kind": "subscription", "pending_purge_days": 10**9}, "pending_purge_days"),
        (form_config(public_fields=["name", "name"]), "twice"),
        (form_config(consent={"required": False, "text": {"EN!": "x"}}), "locale"),
        (form_config(consent={"required": False, "text": {"en": "x" * 2001}}), "2000"),
        (form_config(consent={"required": False, "text": {"en": "a\x00b"}}), "NUL"),
        (form_config(consent={"required": True, "text": {}}), "text"),
        ({"kind": "subscription", "double_opt_in": False}, "consent"),
    ],
)
async def test_a_malformed_config_is_a_422_naming_it(client, config, needle):
    fields = [] if config.get("kind") == "subscription" else None
    resp = await create(client, fields=fields, config=config)
    assert resp.status_code == 422, resp.text
    assert resp.json()["errors"][0]["field"] == "public_submissions"
    assert needle in _message(resp)


async def test_recipients_are_trimmed_and_deduplicated(client):
    resp = await create(client, config=form_config(notify_to=[" a@x.io", "a@x.io", "b@x.io"]))
    assert resp.json()["public_submissions"]["notify_to"] == ["a@x.io", "b@x.io"]


async def test_a_public_field_must_be_submittable(client):
    fields = [*contact_fields(), field("extra", "json", indexed=False)]
    resp = await create(client, fields=fields, config=form_config(public_fields=["extra"]))
    assert resp.status_code == 422
    assert "json field" in _message(resp)


async def test_a_unique_field_cannot_be_public(client):
    """A duplicate would be a 409 telling a visitor what is already stored."""
    fields = [*contact_fields(), field("ref", unique=True)]
    resp = await create(client, fields=fields, config=form_config(public_fields=["ref"]))
    assert resp.status_code == 422
    assert "is unique" in _message(resp)


async def test_a_system_field_cannot_be_public(client):
    resp = await create(client, config=form_config(public_fields=["sm_ip_hash"]))
    assert resp.status_code == 422
    assert "system field" in _message(resp)


async def test_a_public_field_that_does_not_exist_is_dropped(client):
    resp = await create(client, config=form_config(public_fields=["name", "nope"]))
    assert resp.status_code == 201
    assert resp.json()["public_submissions"]["public_fields"] == ["name"]


async def test_enabled_needs_every_required_field_public(client):
    resp = await create(client, config=form_config(enabled=True, public_fields=["name", "email"]))
    assert resp.status_code == 422
    assert "message" in _message(resp)
    # ``triage`` is required-free with a default, and never needs to be public.
    ok = await create(client, config=form_config(enabled=True))
    assert ok.status_code == 201, ok.text


async def test_a_required_field_with_a_default_need_not_be_public(client):
    fields = contact_fields()
    fields[2]["default"] = "(no message)"
    resp = await create(client, fields=fields, config=form_config(enabled=True))
    assert resp.status_code == 201, resp.text


async def test_adding_a_required_private_field_is_refused_while_enabled(client):
    created = (await create(client, config=form_config(enabled=True))).json()
    resp = await update(
        client, "contact", fields=[*created["fields"], field("phone", required=True)]
    )
    assert resp.status_code == 422
    assert "phone" in _message(resp)


async def test_removing_a_field_takes_it_off_the_form(client):
    created = (await create(client)).json()
    kept = [entry for entry in created["fields"] if entry["key"] != "message"]
    resp = await update(client, "contact", fields=kept)
    assert resp.status_code == 200, resp.text
    assert resp.json()["public_submissions"]["public_fields"] == ["name", "email"]


async def test_retyping_a_public_field_to_json_is_refused(client):
    created = (await create(client)).json()
    fields = [dict(entry) for entry in created["fields"]]
    fields[0].update(type="json", indexed=False, required=False)
    resp = await update(client, "contact", fields=fields)
    assert resp.status_code == 422
    assert "json field" in _message(resp)


async def test_public_and_submissions_exclude_each_other(client):
    assert (await create(client, is_public=True)).status_code == 409
    await create(client)
    resp = await update(client, "contact", is_public=True)
    assert resp.status_code == 409
    assert "cannot also be public" in _message(resp)


async def test_turning_an_existing_public_type_into_a_form_is_refused(client):
    await client.post(
        API,
        json={"key": "pub", "label": "Pub", "fields": contact_fields(), "is_public": True},
        headers=roles(ADMIN),
    )
    resp = await update(client, "pub", public_submissions=form_config())
    assert resp.status_code == 409


async def test_the_kind_is_set_once(client):
    await create(client)
    changed = await update(client, "contact", public_submissions={"kind": "subscription"})
    assert changed.status_code == 409
    cleared = await update(client, "contact", public_submissions=None)
    assert cleared.status_code == 409
    assert "cannot be turned off" in _message(cleared)


async def test_a_config_edit_is_not_a_schema_change(client):
    created = (await create(client)).json()
    resp = await update(
        client, "contact", public_submissions=form_config(enabled=True, notify_to=["a@x.io"])
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schema_version"] == created["schema_version"]
    assert body["version"] == created["version"] + 1
    assert body["public_submissions"]["enabled"] is True
    revisions = await client.get(f"{API}/contact/revisions", headers=roles(ADMIN))
    assert len(revisions.json()["items"]) == 1


async def test_an_ordinary_type_echoing_null_is_unaffected(client):
    await client.post(
        API, json={"key": "plain", "label": "Plain", "fields": []}, headers=roles(ADMIN)
    )
    resp = await update(client, "plain", public_submissions=None, label="Plainer")
    assert resp.status_code == 200, resp.text
    assert resp.json()["public_submissions"] is None


async def test_the_config_travels_with_an_exported_definition(client):
    await create(client, config=form_config(notify_to=["a@x.io"]))
    exported = (await client.get(f"{API}/contact/export", headers=roles(ADMIN))).json()
    assert exported["public_submissions"]["notify_to"] == ["a@x.io"]
    exported["key"] = "contact_copy"
    resp = await client.post(f"{API}/import", json=exported, headers=roles(ADMIN))
    assert resp.status_code in (200, 201), resp.text
    assert resp.json()["public_submissions"] == exported["public_submissions"]
    assert [e["key"] for e in resp.json()["fields"]] == [e["key"] for e in exported["fields"]]
