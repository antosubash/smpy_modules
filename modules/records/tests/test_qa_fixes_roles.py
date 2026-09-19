"""Regressions for the QA pass's F4 — ``allowed_roles`` and the wide writes.

A type's ``allowed_roles`` narrows the static ``records.edit`` /
``records.manage_types`` permissions (README § Permissions), and narrowing has
no exceptions: the ``admin`` wildcard is not a bypass. It reached every record
write and a cascade into the type, but not the two widest writes of all —
``DELETE /api/records/types/{key}``, which purges every record the type holds,
trash included, and ``orphaned: "discard"``, the one bulk payload write in
design §8. Both are gated now by the same ``deps.check_type_roles`` a single
record write goes through, with its admin semantics unchanged.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_MANAGER, roles

_FIELDS = [{"key": "name", "type": "text", "label": "Name"}]


async def _type_with_roles(client, key: str, allowed: list[str], *, actor: str = ADMIN):
    resp = await client.post(
        "/api/records/types",
        json={"key": key, "label": key.title(), "fields": _FIELDS, "allowed_roles": allowed},
        headers=roles(actor),
    )
    assert resp.status_code == 201
    return resp.json()


async def test_type_delete_is_refused_for_a_caller_outside_allowed_roles(client):
    await _type_with_roles(client, "narrow", [ROLE_EDITOR])
    resp = await client.delete(
        "/api/records/types/narrow?confirm_record_count=0", headers=roles(ROLE_MANAGER)
    )
    assert resp.status_code == 403
    # The type is still there: a refused delete writes nothing.
    still = await client.get("/api/records/types/narrow", headers=roles(ROLE_MANAGER))
    assert still.status_code == 200


async def test_type_delete_is_refused_for_the_admin_wildcard_too(client):
    """Narrowing has no exceptions — the README's rule, unchanged. ``admin``
    resolves to the wildcard permission and is still not in the list."""
    await _type_with_roles(client, "narrow", [ROLE_MANAGER])
    resp = await client.delete(
        "/api/records/types/narrow?confirm_record_count=0", headers=roles(ADMIN)
    )
    assert resp.status_code == 403


async def test_type_delete_succeeds_for_a_caller_the_list_includes(client):
    await _type_with_roles(client, "narrow", [ROLE_MANAGER])
    resp = await client.delete(
        "/api/records/types/narrow?confirm_record_count=0", headers=roles(ROLE_MANAGER)
    )
    assert resp.status_code == 204


async def test_type_delete_is_unaffected_when_allowed_roles_is_empty(client):
    await _type_with_roles(client, "open", [])
    resp = await client.delete(
        "/api/records/types/open?confirm_record_count=0", headers=roles(ROLE_MANAGER)
    )
    assert resp.status_code == 204


async def test_type_delete_still_purges_the_records_it_is_allowed_to(client):
    """The count confirmation and the purge are unchanged — the role check is
    a gate in front of them, not a replacement for them."""
    await _type_with_roles(client, "narrow", [ROLE_MANAGER])
    await client.post(
        "/api/records/types/narrow/records",
        json={"data": {"name": "a"}},
        headers=roles(ROLE_MANAGER),
    )
    stale = await client.delete(
        "/api/records/types/narrow?confirm_record_count=0", headers=roles(ROLE_MANAGER)
    )
    assert stale.status_code == 409
    ok = await client.delete(
        "/api/records/types/narrow?confirm_record_count=1", headers=roles(ROLE_MANAGER)
    )
    assert ok.status_code == 204


async def _type_with_orphaned_value(client, key: str) -> int:
    """Create ``key`` with two fields, write a record, then drop one field —
    leaving an orphaned value under the dropped key. Returns the type version.
    """
    created = await client.post(
        "/api/records/types",
        json={
            "key": key,
            "label": key.title(),
            "fields": [
                {"key": "name", "type": "text", "label": "Name"},
                {"key": "price", "type": "number", "label": "Price"},
            ],
        },
        headers=roles(ADMIN),
    )
    assert created.status_code == 201
    await client.post(
        f"/api/records/types/{key}/records",
        json={"data": {"name": "a", "price": "1.5"}},
        headers=roles(ADMIN),
    )
    dropped = await client.put(
        f"/api/records/types/{key}",
        json={"expected_version": created.json()["version"], "fields": _FIELDS},
        headers=roles(ADMIN),
    )
    assert dropped.status_code == 200
    return dropped.json()["version"]


async def test_orphaned_discard_meets_allowed_roles(client):
    """§8.8's ``discard`` is a bulk write over this type's records, so
    ``records.manage_types`` alone is not enough for a type whose records the
    caller may not write."""
    version = await _type_with_orphaned_value(client, "orph")
    readd = {
        "expected_version": version,
        "fields": [
            {"key": "name", "type": "text", "label": "Name"},
            {"key": "price", "type": "number", "label": "Price"},
        ],
    }
    conflict = await client.put("/api/records/types/orph", json=readd, headers=roles(ROLE_MANAGER))
    assert conflict.status_code == 409
    assert conflict.json()["conflicts"] == {"price": 1}

    # Narrow the type to a role the manager does not hold (a plain column
    # edit: not a discard, so it is not itself gated).
    narrowed = await client.put(
        "/api/records/types/orph",
        json={"expected_version": version, "allowed_roles": [ROLE_EDITOR]},
        headers=roles(ROLE_MANAGER),
    )
    assert narrowed.status_code == 200
    readd["expected_version"] = narrowed.json()["version"]

    refused = await client.put(
        "/api/records/types/orph",
        json={**readd, "orphaned": "discard"},
        headers=roles(ROLE_MANAGER),
    )
    assert refused.status_code == 403


async def test_orphaned_discard_is_allowed_for_a_caller_the_list_includes(client):
    version = await _type_with_orphaned_value(client, "orph")
    narrowed = await client.put(
        "/api/records/types/orph",
        json={"expected_version": version, "allowed_roles": [ROLE_MANAGER]},
        headers=roles(ROLE_MANAGER),
    )
    assert narrowed.status_code == 200
    resp = await client.put(
        "/api/records/types/orph",
        json={
            "expected_version": narrowed.json()["version"],
            "fields": [
                {"key": "name", "type": "text", "label": "Name"},
                {"key": "price", "type": "number", "label": "Price"},
            ],
            "orphaned": "discard",
        },
        headers=roles(ROLE_MANAGER),
    )
    assert resp.status_code == 200


async def test_an_ordinary_schema_edit_is_not_gated_by_allowed_roles(client):
    """The narrowing reaches the writes that touch *records*. A label or
    ``fields`` edit writes the type row, and stays on ``records.manage_types``
    alone — changing that would lock an operator out of the screen that fixes
    ``allowed_roles``."""
    created = await _type_with_roles(client, "narrow", [ROLE_EDITOR])
    resp = await client.put(
        "/api/records/types/narrow",
        json={"expected_version": created["version"], "label": "Renamed"},
        headers=roles(ROLE_MANAGER),
    )
    assert resp.status_code == 200


async def test_record_purge_still_meets_allowed_roles(client):
    """Already guarded before this pass; pinned so it stays that way."""
    await _type_with_roles(client, "narrow", [ROLE_EDITOR])
    created = await client.post(
        "/api/records/types/narrow/records",
        json={"data": {"name": "a"}},
        headers=roles(ROLE_EDITOR),
    )
    uuid = created.json()["uuid"]
    await client.delete(f"/api/records/types/narrow/records/{uuid}", headers=roles(ROLE_EDITOR))
    resp = await client.delete(
        f"/api/records/types/narrow/records/{uuid}/purge", headers=roles(ROLE_MANAGER)
    )
    assert resp.status_code == 403
