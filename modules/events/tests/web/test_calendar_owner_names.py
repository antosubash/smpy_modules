"""The calendar list names its owners; a label that is an address is never shown."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.support.app import Directory
from tests.support.calendars import BASE, EDITOR, MANAGER, OWNER, make

USERS = {
    "o": ("o@example.com", "Olga Owner", True),
    "e": ("eve@example.com", "Eve Editor", True),
    "m": ("mia@example.com", "mia@example.com", True),
    "gone": ("gone@example.com", "Gone Person", False),
}


def _by_name(rows):
    return {row["name"]: row for row in rows}


async def test_owner_names_self_other_address_label_and_unknown(client):
    client.app.state.user_directory = Directory(USERS)
    await make(client, OWNER, name="Mine")
    await make(client, EDITOR, name="Eves")
    await make(client, {**OWNER, "X-Test-User": "m"}, name="Addr")
    await make(client, {**OWNER, "X-Test-User": "gone"}, name="Inactive")
    await make(client, {**OWNER, "X-Test-User": "ghost"}, name="Unknown")
    got = await client.get(BASE, headers={**OWNER, "X-Test-Perms": "events.view,events.manage"})
    rows = _by_name(got.json())
    assert rows["Mine"]["owner_name"] == "Olga Owner"
    assert rows["Eves"]["owner_name"] == "Eve Editor"
    assert rows["Addr"]["owner_name"] is None
    assert rows["Inactive"]["owner_name"] is None
    assert rows["Unknown"]["owner_name"] is None
    assert "mia@example.com" not in got.text
    assert "m***@" not in got.text


async def test_single_calendar_carries_owner_name(client):
    client.app.state.user_directory = Directory(USERS)
    made = await make(client, EDITOR, name="Eves")
    assert made["owner_name"] == "Eve Editor"
    got = await client.get(f"{BASE}/{made['id']}", headers=EDITOR)
    assert got.json()["owner_name"] == "Eve Editor"


async def test_no_directory_means_no_owner_name(client):
    made = await make(client, OWNER)
    assert made["owner_name"] is None
    got = await client.get(BASE, headers=OWNER)
    assert got.status_code == 200


@pytest.mark.unbound_tenant
async def test_multi_tenant_names_only_members(multi_client):
    client = multi_client
    client.app.state.user_directory = Directory(
        {**USERS, "x": ("x@example.com", "Xavier Other", True)}
    )
    members = {"a": {"o", "e", "gone", "m"}, "b": {"x"}}
    batches: list[int] = []

    async def tenant_members(db, tenant_id, ids):
        batches.append(len(ids))
        return {i for i in ids if i in members[tenant_id]}

    client.app.state.tenant_members = tenant_members
    mine = {**OWNER, "X-Test-Tenant": "a"}
    for uid, name in (("o", "Mine"), ("x", "Foreign"), ("gone", "Inactive")):
        made = await client.post(
            BASE,
            json={"name": name, "visibility": "internal"},
            headers={**mine, "X-Test-User": uid},
        )
        assert made.status_code == 201, made.text
    batches.clear()
    got = await client.get(BASE, headers={**mine, "X-Test-User": "o"})
    rows = _by_name(got.json())
    assert rows["Mine"]["owner_name"] == "Olga Owner"
    assert rows["Foreign"]["owner_name"] is None
    assert rows["Inactive"]["owner_name"] is None
    assert len(batches) == 1


class _Raising(Directory):
    async def get_many(self, db, ids, *, with_roles=False):
        raise RuntimeError("directory down")


async def test_failing_directory_leaves_names_null_on_list_get_and_patch(client):
    made = await make(client, EDITOR, name="Eves")
    client.app.state.user_directory = _Raising(USERS)
    listed = await client.get(BASE, headers=EDITOR)
    assert listed.status_code == 200
    assert [r["owner_name"] for r in listed.json()] == [None]
    got = await client.get(f"{BASE}/{made['id']}", headers=EDITOR)
    assert (got.status_code, got.json()["owner_name"]) == (200, None)
    patched = await client.patch(f"{BASE}/{made['id']}", json={"name": "Renamed"}, headers=EDITOR)
    assert (patched.status_code, patched.json()["owner_name"]) == (200, None)


@pytest.mark.unbound_tenant
async def test_failing_membership_store_leaves_names_null(multi_client):
    client = multi_client
    client.app.state.user_directory = Directory(USERS)
    mine = {**OWNER, "X-Test-Tenant": "a"}

    async def member(db, tenant_id, ids):
        return set(ids)

    client.app.state.tenant_members = member
    made = await client.post(BASE, json={"name": "T", "visibility": "internal"}, headers=mine)
    assert made.status_code == 201, made.text

    async def tenant_members(db, tenant_id, ids):
        raise RuntimeError("membership down")

    client.app.state.tenant_members = tenant_members
    got = await client.get(BASE, headers=mine)
    assert got.status_code == 200
    assert [r["owner_name"] for r in got.json()] == [None]


async def test_failing_directory_never_allows_an_ownership_transfer(client):
    cid = (await make(client))["id"]
    client.app.state.user_directory = _Raising(USERS)
    with pytest.raises(RuntimeError):
        await client.put(f"{BASE}/{cid}/owner", json={"owner_id": "e"}, headers=MANAGER)
    client.app.state.user_directory = Directory(USERS)
    assert (await client.get(f"{BASE}/{cid}", headers=OWNER)).json()["owner_id"] == "o"


class _SqlFailing(Directory):
    """A lookup whose statement fails on the session it is handed."""

    async def get_many(self, db, ids, *, with_roles=False):
        await db.execute(text("SELECT * FROM no_such_table_owner_lookup"))
        return await super().get_many(db, ids, with_roles=with_roles)


async def test_failed_sql_in_the_lookup_does_not_abort_the_list(client):
    await make(client, EDITOR, name="Eves")
    client.app.state.user_directory = _SqlFailing(USERS)
    listed = await client.get(BASE, headers=EDITOR)
    assert listed.status_code == 200
    assert [r["owner_name"] for r in listed.json()] == [None]
    client.app.state.user_directory = Directory(USERS)
    assert (await client.get(BASE, headers=EDITOR)).json()[0]["owner_name"] == "Eve Editor"


async def test_failed_sql_in_the_lookup_keeps_a_patched_name(client):
    made = await make(client, EDITOR, name="Eves")
    client.app.state.user_directory = _SqlFailing(USERS)
    patched = await client.patch(f"{BASE}/{made['id']}", json={"name": "Renamed"}, headers=EDITOR)
    assert (patched.status_code, patched.json()["owner_name"]) == (200, None)
    client.app.state.user_directory = Directory(USERS)
    got = await client.get(f"{BASE}/{made['id']}", headers=EDITOR)
    assert got.json()["name"] == "Renamed"


async def test_a_failed_lookup_logs_only_the_exception_class(client, caplog):
    await make(client, EDITOR, name="Eves")
    client.app.state.user_directory = _Raising(USERS)
    with caplog.at_level("WARNING", logger="sm_events.web.services.owners"):
        await client.get(BASE, headers=EDITOR)
    records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert records and all(r.exc_info is None for r in records)
    assert "directory down" not in caplog.text
    assert "RuntimeError" in caplog.text
