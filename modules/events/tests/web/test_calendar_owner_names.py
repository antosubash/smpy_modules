"""The calendar list names its owners, under the share picker's disclosure rule."""

from __future__ import annotations

import pytest

from tests.support.app import Directory
from tests.support.calendars import BASE, EDITOR, OWNER, make

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
    assert rows["Addr"]["owner_name"] == "m***@example.com"
    assert rows["Inactive"]["owner_name"] is None
    assert rows["Unknown"]["owner_name"] is None
    assert "mia@example.com" not in got.text


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
