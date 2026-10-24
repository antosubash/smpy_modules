"""System values are written only through ``system=`` (#101, design §3.2):
an admin write, an import or a bulk action can neither set nor change one."""

from __future__ import annotations

import json

import pytest
from sm_records.services import records as service
from sm_records.services import types as type_service
from sm_records.services.errors import ValidationFailed
from sm_records.tenancy import tenant_scope

from tests.app_harness import ADMIN, roles
from tests.io_helpers import post_import
from tests.public_submissions_support import API, contact_fields, create, form_config

DATA = {"name": "Ada", "email": "ada@x.io", "message": "hello"}


@pytest.fixture
async def contact(db, settings):
    return await type_service.create_type(
        db,
        key="contact",
        label="Contact",
        fields_raw=contact_fields(),
        public_submissions=form_config(),
        settings=settings,
    )


async def test_system_values_are_written_through_system(db, settings, contact):
    record = await service.create_record(
        db, contact, data=dict(DATA), settings=settings, system={"sm_source_page": "/contact"}
    )
    assert record.data["sm_source_page"] == "/contact"
    updated = await service.update_record(
        db,
        contact,
        record,
        expected_version=record.version,
        data=dict(DATA),
        settings=settings,
        system={"sm_notified_at": "2026-10-24T12:00:00+00:00"},
    )
    assert updated.data["sm_source_page"] == "/contact"
    assert updated.data["sm_notified_at"].startswith("2026-10-24T12:00:00")


async def test_system_values_are_validated(db, settings, contact):
    with pytest.raises(ValidationFailed):
        await service.create_record(
            db, contact, data=dict(DATA), settings=settings, system={"sm_spam": "maybe"}
        )


async def test_system_names_only_system_fields(db, settings, contact):
    with pytest.raises(ValueError, match="not system fields"):
        await service.create_record(
            db, contact, data=dict(DATA), settings=settings, system={"name": "Eve"}
        )


async def test_a_create_drops_client_system_values(db, settings, contact):
    record = await service.create_record(
        db, contact, data={**DATA, "sm_spam": "manual"}, settings=settings
    )
    assert record.data.get("sm_spam") is None


async def test_an_update_keeps_the_stored_system_values(db, settings, contact):
    record = await service.create_record(
        db, contact, data=dict(DATA), settings=settings, system={"sm_source_page": "/a"}
    )
    for sent in ({"sm_source_page": "/forged"}, {"sm_source_page": None}, {}):
        record = await service.update_record(
            db,
            contact,
            record,
            expected_version=record.version,
            data={**DATA, **sent},
            settings=settings,
        )
        assert record.data["sm_source_page"] == "/a"


async def _seed(client, records_app) -> str:
    """A form type and one submission, written as the public endpoint will."""
    assert (await create(client)).status_code == 201
    app, db_state = records_app
    async with db_state.session_factory() as db:
        with tenant_scope("default"):
            rtype = await type_service.get_type(db, "contact")
            record = await service.create_record(
                db,
                rtype,
                data=dict(DATA),
                settings=app.state.sm_records.settings,
                system={"sm_source_page": "/contact", "sm_spam": "links"},
            )
            await db.commit()
            return record.uuid


async def test_the_admin_api_cannot_change_system_values(client, records_app):
    uuid = await _seed(client, records_app)
    url = f"{API}/contact/records/{uuid}"
    current = (await client.get(url, headers=roles(ADMIN))).json()
    resp = await client.put(
        url,
        json={
            "expected_version": current["version"],
            "data": {**current["data"], "sm_source_page": "/forged", "sm_spam": None},
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["sm_source_page"] == "/contact"
    assert resp.json()["data"]["sm_spam"] == "links"


async def test_an_admin_create_drops_system_values(client):
    await create(client)
    resp = await client.post(
        f"{API}/contact/records",
        json={"data": {**DATA, "sm_source_page": "/forged"}},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["data"]["sm_source_page"] is None


async def test_a_bulk_action_leaves_system_values_alone(client, records_app):
    uuid = await _seed(client, records_app)
    resp = await client.post(
        f"{API}/contact/records/bulk",
        json={"action": "publish", "uuids": [uuid]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    read = (await client.get(f"{API}/contact/records/{uuid}", headers=roles(ADMIN))).json()
    assert read["data"]["sm_source_page"] == "/contact"


async def test_an_import_cannot_write_system_values(client):
    await create(client)
    rows = [{"data": {**DATA, "sm_spam": "manual"}}]
    resp = await post_import(client, "contact", json.dumps({"records": rows}), dry_run="false")
    assert resp.status_code == 200, resp.text
    listed = (await client.get(f"{API}/contact/records", headers=roles(ADMIN))).json()
    assert [item["data"].get("sm_spam") for item in listed["items"]] == [None]


async def test_the_export_leaves_internal_fields_out(client):
    resp = await create(client, "news", fields=[], config={"kind": "subscription"})
    assert resp.status_code == 201
    csv = await client.get(f"{API}/news/records/export?format=csv", headers=roles(ADMIN))
    assert csv.status_code == 200, csv.text
    header = csv.text.splitlines()[0].split(",")
    assert "sm_email" in header and "sm_status" in header
    assert "sm_nonce" not in header
