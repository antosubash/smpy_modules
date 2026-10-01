"""MAJOR 1 / MINOR 1: the type-import path, and who may read a definition.

``POST /types/import`` with ``mode=update`` used to write the *class
defaults* of every key the body omitted, so a definition that simply did not
mention ``allowed_roles`` cleared a type's narrowing and unpublished it into
the bargain — the one schema write that did not have to name what it was
changing. And the three routes that serve a definition (``GET /types/{key}``,
its ``/revisions`` and its ``/export``) asked for ``records.view`` alone,
where the editor over the same object asks for ``records.manage_types``.
"""

from __future__ import annotations

from tests.app_harness import (
    ADMIN,
    ROLE_EDITOR,
    ROLE_MANAGER,
    ROLE_VIEWER,
    api_record,
    api_type,
    roles,
)

_API = "/api/records/types"
_FIELDS = [{"key": "name", "type": "text", "label": "Name", "indexed": True}]


# --- MAJOR 1: mode=update writes what was sent, and nothing else -----------


async def _narrow(client, key: str = "narrow") -> dict:
    return await api_type(
        client,
        key,
        _FIELDS,
        actor=f"{ADMIN},{ROLE_EDITOR}",
        allowed_roles=[ROLE_EDITOR, ROLE_MANAGER],
        is_public=True,
        translatable=True,
        display_field="name",
        description="keep me",
    )


async def test_type_import_update_keeps_every_key_the_body_omits(client):
    """``exclude_unset``, exactly as ``PUT /types/{key}`` — a definition that
    does not mention ``allowed_roles`` is not a request to clear it."""
    before = await _narrow(client)
    resp = await client.post(
        f"{_API}/import",
        json={
            "mode": "update",
            "key": "narrow",
            "label": "Renamed",
            "label_plural": "Renamed",
            "fields": _FIELDS,
            "expected_version": before["version"],
        },
        headers=roles(ROLE_MANAGER),
    )
    assert resp.status_code == 200, resp.text
    after = resp.json()
    assert after["label"] == "Renamed"
    assert after["allowed_roles"] == [ROLE_EDITOR, ROLE_MANAGER]
    assert after["is_public"] is True
    assert after["translatable"] is True
    assert after["display_field"] == "name"
    assert after["description"] == "keep me"


async def test_an_export_round_trips_through_mode_update(client):
    """The other half: an export carries *every* field, so re-importing one
    must still be an ordinary update — the narrowing it sends is the one
    already stored, so nothing new is being asked for."""
    before = await _narrow(client, "roundtrip")
    exported = await client.get(f"{_API}/roundtrip/export", headers=roles(ROLE_MANAGER))
    assert exported.status_code == 200, exported.text
    body = {**exported.json(), "mode": "update", "expected_version": before["version"]}
    resp = await client.post(f"{_API}/import", json=body, headers=roles(ROLE_MANAGER))
    assert resp.status_code == 200, resp.text
    after = resp.json()
    assert after["allowed_roles"] == [ROLE_EDITOR, ROLE_MANAGER]
    assert after["is_public"] is True
    assert after["description"] == "keep me"


async def test_changing_allowed_roles_by_import_costs_the_narrowing(client):
    """A *different* list is a request to change the narrowing, and a caller
    the current list excludes does not get to make it as a side effect of
    importing a file. The schema editor's ``PUT`` is where that is asked for
    deliberately (README § Permissions)."""
    before = await _narrow(client, "guarded")
    definition = {
        "mode": "update",
        "key": "guarded",
        "label": "Guarded",
        "label_plural": "Guardeds",
        "fields": _FIELDS,
        "expected_version": before["version"],
        "allowed_roles": [],
    }
    refused = await client.post(f"{_API}/import", json=definition, headers=roles(ADMIN))
    assert refused.status_code == 403, refused.text

    allowed = await client.post(f"{_API}/import", json=definition, headers=roles(ROLE_MANAGER))
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["allowed_roles"] == []


# --- MINOR 1: the schema reads narrow like every other read ---------------


async def test_the_schema_reads_apply_allowed_roles(client):
    await _narrow(client, "secret")
    for i in range(3):
        await api_record(client, "secret", {"name": f"r{i}"}, actor=ROLE_EDITOR)

    for path in ("", "/revisions", "/export"):
        refused = await client.get(f"{_API}/secret{path}", headers=roles(ROLE_VIEWER))
        assert refused.status_code == 403, (path, refused.text)


async def test_manage_types_still_reads_a_type_it_is_excluded_from(client):
    """The one exception, and the same one ``views_types`` makes: the manager
    locked out of the screen that edits ``allowed_roles`` is a one-way door.
    ``records-manager`` is not on this type's list."""
    await api_type(
        client,
        "walled",
        _FIELDS,
        actor=f"{ADMIN},{ROLE_EDITOR}",
        allowed_roles=[ROLE_EDITOR],
        display_field="name",
    )
    for path in ("", "/revisions", "/export"):
        resp = await client.get(f"{_API}/walled{path}", headers=roles(ROLE_MANAGER))
        assert resp.status_code == 200, (path, resp.text)
