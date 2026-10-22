"""Restoring what a schema change left behind: orphaned values, old record
revisions, and a rollback to the schema already in place.

Type keys are unique across the suite on purpose — ``schema.compile``'s model
cache is process-global.
"""

from __future__ import annotations

from tests.app_harness import ADMIN, roles, seed_record, seed_type

API = "/api/records"


def _field(key: str, type_: str = "text", **cols) -> dict:
    return {"key": key, "type": type_, "label": key.title(), "indexed": True, **cols}


# --- orphaned values are dry-run before they are restored (§8.8) --------


async def test_restoring_orphaned_values_reports_the_ones_that_do_not_validate(client):
    """Re-adding a deleted key is classified ADDITIVE, so nothing scanned the
    values that key still holds — and ``restore`` claimed ``failing=0`` while
    handing back ``"oops"`` as a ``number``."""
    rtype = await seed_type(
        client.db_state, "r2orph", [_field("name"), _field("price")], display_field="name"
    )
    for i, price in enumerate(["12", "oops", "nope"]):
        await seed_record(client.db_state, rtype, {"name": f"n{i}", "price": price})

    resp = await client.put(
        f"{API}/types/r2orph",
        json={"expected_version": 1, "fields": [_field("name")]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text

    new_fields = [_field("name"), _field("price", "number")]
    resp = await client.post(
        f"{API}/types/r2orph/schema/preview", json={"fields": new_fields}, headers=roles(ADMIN)
    )
    report = resp.json()["report"]
    assert report == {**report, "checked": 3, "failing": 2}
    assert report["orphaned_conflicts"] == {"price": 3}
    assert report["sample"][0]["errors"] == [{"field": "price", "message": "not a number"}]

    body = {"expected_version": 2, "fields": new_fields, "orphaned": "restore"}
    resp = await client.put(f"{API}/types/r2orph", json=body, headers=roles(ADMIN))
    assert resp.status_code == 409, resp.text
    assert resp.json()["report"]["failing"] == 2

    resp = await client.put(
        f"{API}/types/r2orph", json={**body, "force": True}, headers=roles(ADMIN)
    )
    assert resp.status_code == 200, resp.text
    items = (await client.get(f"{API}/types/r2orph/records", headers=roles(ADMIN))).json()["items"]
    marked = 0
    for item in items:
        url = f"{API}/types/r2orph/records/{item['uuid']}"
        marked += bool((await client.get(url, headers=roles(ADMIN))).json()["invalid"])
    assert marked == 2


# --- a revision older than a field deletion is still restorable ---------


async def test_restoring_a_revision_taken_before_a_field_was_deleted(client):
    """The snapshot still carries the deleted key at top level and the
    compiled validator is ``extra="forbid"``, which made every such restore a
    permanent 422. The undeclared half goes under ``_orphaned`` instead."""
    await seed_type(
        client.db_state, "r2rev", [_field("name"), _field("note")], display_field="name"
    )
    created = await client.post(
        f"{API}/types/r2rev/records",
        json={"data": {"name": "a", "note": "keep me"}},
        headers=roles(ADMIN),
    )
    uuid = created.json()["uuid"]
    resp = await client.put(
        f"{API}/types/r2rev/records/{uuid}",
        json={"expected_version": 1, "data": {"name": "b", "note": "later"}},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    revisions = (
        await client.get(f"{API}/types/r2rev/records/{uuid}/revisions", headers=roles(ADMIN))
    ).json()["items"]
    first = next(item for item in revisions if item["version"] == 1)

    resp = await client.put(
        f"{API}/types/r2rev",
        json={"expected_version": 1, "fields": [_field("name")]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text

    resp = await client.post(
        f"{API}/types/r2rev/records/{uuid}/revisions/{first['id']}/restore",
        json={"expected_version": 2},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    # Nothing from the revision is dropped: ``name`` is the write, ``note`` is
    # recovery data — and it is the *revision's* value, not the later edit's.
    assert resp.json()["data"] == {"name": "a", "_orphaned": {"note": "keep me"}}
    events = [
        item["event"]
        for item in (
            await client.get(f"{API}/types/r2rev/records/{uuid}/revisions", headers=roles(ADMIN))
        ).json()["items"]
    ]
    assert events[0] == "restore"


# --- a no-op schema change is not a schema change -----------------------


async def test_a_rollback_to_the_current_schema_only_bumps_the_version(client):
    """``apply`` bumped ``schema_version`` whenever ``fields`` was passed at
    all, and ``rollback`` always passes it — so undoing to where you already
    are marked every record stale and snapshotted a duplicate revision."""
    fields = [_field("name")]
    created = await client.post(
        f"{API}/types",
        json={"key": "r2noop", "label": "Noop", "fields": fields, "display_field": "name"},
        headers=roles(ADMIN),
    )
    assert created.status_code == 201, created.text
    await client.post(
        f"{API}/types/r2noop/records", json={"data": {"name": "a"}}, headers=roles(ADMIN)
    )
    before = (await client.get(f"{API}/types/r2noop", headers=roles(ADMIN))).json()
    revisions = (await client.get(f"{API}/types/r2noop/revisions", headers=roles(ADMIN))).json()

    resp = await client.post(
        f"{API}/types/r2noop/revisions/1/restore",
        json={"expected_version": before["version"]},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["schema_version"] == before["schema_version"]
    assert resp.json()["version"] == before["version"] + 1
    assert resp.json()["reindex_pending"] == {}

    after = (await client.get(f"{API}/types/r2noop/revisions", headers=roles(ADMIN))).json()
    assert len(after["items"]) == len(revisions["items"])
    listed = (await client.get(f"{API}/types/r2noop/records", headers=roles(ADMIN))).json()["items"]
    assert [item["schema_stale"] for item in listed] == [False]
