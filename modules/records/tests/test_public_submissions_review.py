"""Write paths around a newsletter type's system fields (#101, review of #232):
an import plans with the values the write will carry, an internal field is
never a title or a slug, and a newsletter's records are not translated."""

from __future__ import annotations

import json

import pytest
from sm_records.services import records as service
from sm_records.services import types as type_service
from sm_records.services.errors import Conflict
from sm_records.tenancy import tenant_scope

from tests.app_harness import ADMIN, field, roles
from tests.io_helpers import export_text, post_import
from tests.public_submissions_support import API, create, form_config, update

SUBSCRIBER = {"sm_email": "ada@x.io", "sm_status": "confirmed", "sm_nonce": "a" * 32}


async def _newsletter(client, records_app) -> str:
    """A newsletter type with one ordinary field and one subscriber."""
    resp = await create(
        client, "news", fields=[field("name", indexed=False)], config={"kind": "subscription"}
    )
    assert resp.status_code == 201, resp.text
    app, db_state = records_app
    async with db_state.session_factory() as db:
        with tenant_scope("default"):
            rtype = await type_service.get_type(db, "news")
            record = await service.create_record(
                db,
                rtype,
                data={"name": "Ada"},
                settings=app.state.sm_records.settings,
                system=dict(SUBSCRIBER),
            )
            await db.commit()
            return record.uuid


async def test_reimporting_an_unchanged_export_changes_nothing(client, records_app):
    uuid = await _newsletter(client, records_app)
    text = await export_text(client, "news")
    assert "sm_nonce" not in json.loads(text)["records"][0]["data"]
    dry = await post_import(client, "news", text)
    assert dry.status_code == 200, dry.text
    report = dry.json()
    assert (report["skipped"], report["updated"], report["errors"]) == (1, 0, [])
    applied = await post_import(client, "news", text, dry_run="false")
    assert applied.status_code == 200, applied.text
    revisions = await client.get(f"{API}/news/records/{uuid}/revisions", headers=roles(ADMIN))
    assert len(revisions.json()["items"]) == 1


async def test_an_import_update_without_the_address_keeps_it(client, records_app):
    uuid = await _newsletter(client, records_app)
    rows = [{"uuid": uuid, "data": {"name": "Ada L."}}]
    resp = await post_import(
        client, "news", json.dumps({"records": rows}), dry_run="false", force="true"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 1
    read = (await client.get(f"{API}/news/records/{uuid}", headers=roles(ADMIN))).json()
    assert read["data"]["name"] == "Ada L."
    assert read["data"]["sm_email"] == "ada@x.io"
    assert read["data"]["sm_nonce"] == "a" * 32


@pytest.mark.parametrize("pointer", ["display_field", "slug_field"])
async def test_an_internal_field_is_never_a_pointer(client, pointer):
    resp = await create(
        client, "news", fields=[], config={"kind": "subscription"}, **{pointer: "sm_nonce"}
    )
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["field"] == pointer
    assert "internal system field" in resp.json()["errors"][0]["message"]
    ok = await create(client, "news", fields=[], config={"kind": "subscription"})
    assert ok.status_code == 201
    refused = await update(client, "news", **{pointer: "sm_nonce"})
    assert refused.status_code == 422


async def test_a_readonly_system_field_may_be_the_title(client):
    resp = await create(
        client, "contact", config={"kind": "form", "public_fields": ["name", "email", "message"]}
    )
    assert resp.status_code == 201
    assert (await update(client, "contact", display_field="sm_source_page")).status_code == 200


async def test_a_newsletter_record_is_not_translated(client, records_app):
    uuid = await _newsletter(client, records_app)
    app, db_state = records_app
    async with db_state.session_factory() as db:
        with tenant_scope("default"):
            rtype = await type_service.get_type(db, "news")
            rtype.translatable = True
            source = await service.get_record(db, rtype, uuid)
            with pytest.raises(Conflict, match="newsletter list"):
                await service.create_translation(
                    db, rtype, source, locale="de", settings=app.state.sm_records.settings
                )


async def test_a_pruned_config_equal_to_the_stored_one_is_saved_pruned(client):
    assert (await create(client)).status_code == 201
    sent = form_config(public_fields=["name", "email", "message", "ghost"])
    resp = await update(client, "contact", public_submissions=sent)
    assert resp.status_code == 200, resp.text
    got = (await client.get(f"{API}/contact", headers=roles(ADMIN))).json()
    assert got["public_submissions"]["public_fields"] == ["name", "email", "message"]
