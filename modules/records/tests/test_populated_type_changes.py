"""Schema and pointer changes on a type that already holds records.

The trash counts towards both the schema-change dry run and the delete
confirmation, and ``display_field``/``slug_field`` stay editable on a populated
type. Type keys are unique across the whole suite on purpose —
``schema.compile``'s model cache is process-global.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, api_record, api_type, roles
from tests.app_harness import field as _field

API = "/api/records"


# --- the trash counts, and the pointers are editable now ----------


async def _one_trashed(client, key: str) -> dict:
    await api_type(client, key, [_field("name", "text"), _field("alt", "text")])
    record = await api_record(client, key, {"name": "Trashed"})
    assert (
        await client.delete(f"{API}/types/{key}/records/{record['uuid']}", headers=roles(ADMIN))
    ).status_code == 204
    read = await client.get(f"{API}/types/{key}", headers=roles(ADMIN))
    assert read.json()["record_count"] == 0
    return read.json()


async def test_the_trash_still_counts_when_a_schema_change_is_classified(client):
    """F4 was "the lock counts the trash". Phase 3 replaced the lock with the
    dry run of design §8.2, and the rule survives the replacement: a trashed
    record still holds content the schema describes and a restore reads it
    back, so a change that would invalidate it is refused for it."""
    rtype = await _one_trashed(client, "f4thing")
    # ``fields_locked`` is gone (Phase 3 dropped it) — the trash still counts
    # towards *this* rule via ``trashed_record_count`` alone.
    assert rtype["trashed_record_count"] == 1

    # The trashed record has no ``alt`` value, so requiring it fails for the
    # only record the type has — which is in the trash.
    resp = await client.put(
        f"{API}/types/f4thing",
        json={
            "expected_version": rtype["version"],
            "fields": [_field("name", "text"), {**_field("alt", "text"), "required": True}],
        },
        headers=roles(ADMIN),
    )
    assert resp.status_code == 409
    assert "would not satisfy the new schema" in resp.json()["detail"]

    after = await client.get(f"{API}/types/f4thing", headers=roles(ADMIN))
    assert after.json()["schema_version"] == 1


async def test_delete_type_confirms_against_the_trash_too(client):
    await _one_trashed(client, "f5thing")
    refused = await client.delete(
        f"{API}/types/f5thing", params={"confirm_record_count": 0}, headers=roles(ADMIN)
    )
    assert refused.status_code == 409
    assert (
        await client.delete(
            f"{API}/types/f5thing", params={"confirm_record_count": 1}, headers=roles(ADMIN)
        )
    ).status_code == 204


async def test_display_and_slug_field_are_editable_on_a_populated_type(client):
    """F6 locked both pointers on a populated type, because Phase 1 had nothing
    that recomputed ``display_title`` for records already written. Phase 3
    does: a ``display_field`` change enqueues a whole-type rebuild (``"*"`` in
    ``reindex_pending``, design §18 Q2), and ``slug_field`` deliberately
    changes nothing already stored — a slug is an address."""
    await api_type(client, "f6thing", [_field("name", "text"), _field("alt", "text")])
    record = await api_record(client, "f6thing", {"name": "One", "alt": "Other"})
    version = (await client.get(f"{API}/types/f6thing", headers=roles(ADMIN))).json()["version"]

    for pointer in ("display_field", "slug_field"):
        resp = await client.put(
            f"{API}/types/f6thing",
            json={"expected_version": version, pointer: "alt"},
            headers=roles(ADMIN),
        )
        assert resp.status_code == 200, (pointer, resp.text)
        version = resp.json()["version"]

    # Neither pointer rewrote the record: the title waits for the rebuild and
    # the slug is not regenerated at all.
    unchanged = await client.get(
        f"{API}/types/f6thing/records/{record['uuid']}", headers=roles(ADMIN)
    )
    assert unchanged.json()["slug"] == record["slug"]
    assert unchanged.json()["version"] == 1

    # A label edit on the same populated type still goes through.
    ok = await client.put(
        f"{API}/types/f6thing",
        json={"expected_version": version, "label": "Renamed"},
        headers=roles(ADMIN),
    )
    assert ok.status_code == 200
    assert ok.json()["label"] == "Renamed"
