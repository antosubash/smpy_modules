"""The history names the member who made each change, by the owner-name rules."""

from __future__ import annotations

import pytest
from sm_events.core.tenancy import tenant_scope
from sm_events.models import Revision

from tests.support.app import Directory, as_user
from tests.support.events_http import BASE, EV, OWNER, E, V, cast, create, create_json, run

USERS = {
    "o": ("o@example.com", "Olga Owner", True),
    "e": ("eve@example.com", "Eve Editor", True),
    "m": ("mia@example.com", "mia@example.com", True),
    "gone": ("gone@example.com", "Gone Person", False),
}


async def add_revisions(client, event_id: str, actors: list[str | None], tenant: str | None = None):
    """History rows 2, 3, ... for the actors, next to the creation's number 1."""
    import uuid

    async def go(db):
        for number, actor in enumerate(actors, start=2):
            db.add(
                Revision(
                    event_id=uuid.UUID(event_id),
                    number=number,
                    action="updated",
                    actor=actor,
                    snapshot={},
                )
            )

    if tenant:
        with tenant_scope(tenant):
            await run(client, go)
    else:
        await run(client, go)


def by_number(rows):
    return {row["number"]: row for row in rows}


async def history(client, event_id: str, headers=OWNER):
    got = await client.get(f"{EV}/{event_id}/revisions", headers=headers)
    assert got.status_code == 200, got.text
    return by_number(got.json())


async def test_names_a_member_and_nulls_everything_else(client):
    client.app.state.user_directory = Directory(USERS)
    cal = (await cast(client))["I"]
    event = await create(client, cal)
    await add_revisions(client, event["id"], ["e", "m", "gone", "ghost", None])
    rows = await history(client, event["id"])
    named = {n: (r["actor"], r["actor_name"], r["system"]) for n, r in rows.items()}
    assert named == {
        1: ("o", "Olga Owner", False),
        2: ("e", "Eve Editor", False),
        3: ("m", None, False),  # the label is an address: never shown
        4: ("gone", None, False),  # inactive
        5: ("ghost", None, False),  # unknown
        6: (None, None, True),  # the beat: no actor at all, not "unknown"
    }
    assert "mia@example.com" not in str(rows) and "m***@" not in str(rows)


async def test_no_directory_means_no_names_and_the_request_succeeds(client):
    cal = (await cast(client))["I"]
    event = await create(client, cal)
    rows = await history(client, event["id"])
    assert rows[1]["actor_name"] is None and rows[1]["system"] is False


async def test_one_directory_call_for_the_whole_history(client):
    calls: list[int] = []

    class Counting(Directory):
        async def get_many(self, db, ids, *, with_roles=False):
            calls.append(len(ids))
            return await super().get_many(db, ids, with_roles=with_roles)

    client.app.state.user_directory = Counting(USERS)
    cal = (await cast(client))["I"]
    event = await create(client, cal)
    await add_revisions(client, event["id"], ["e", "o", "e", "gone", None, "o"])
    calls.clear()
    await history(client, event["id"])
    assert calls == [3]  # the distinct actors, once, however many rows


async def test_a_failing_directory_leaves_names_null(client):
    class Raising(Directory):
        async def get_many(self, db, ids, *, with_roles=False):
            raise RuntimeError("directory down")

    client.app.state.user_directory = Raising(USERS)
    cal = (await cast(client))["I"]
    event = await create(client, cal)
    await add_revisions(client, event["id"], ["e"])
    rows = await history(client, event["id"])
    assert [r["actor_name"] for r in rows.values()] == [None, None]
    assert rows[2]["actor"] == "e"


async def test_the_single_revision_carries_the_name_too(client):
    client.app.state.user_directory = Directory(USERS)
    cal = (await cast(client))["I"]
    event = await create(client, cal)
    got = await client.get(f"{EV}/{event['id']}/revisions/1", headers=OWNER)
    assert (got.json()["actor_name"], got.json()["system"]) == ("Olga Owner", False)


@pytest.mark.unbound_tenant
async def test_a_non_member_actor_is_not_named(multi_client):
    client = multi_client
    client.app.state.user_directory = Directory(
        {**USERS, "x": ("x@example.com", "Xavier Other", True)}
    )
    members = {"a": {"o", "e"}, "b": {"x"}}

    async def tenant_members(db, tenant_id, ids):
        return {i for i in ids if i in members[tenant_id]}

    client.app.state.tenant_members = tenant_members
    owner = as_user("o", V, E, tenant="a")
    cid = (await client.post(f"{BASE}/calendars", json={"name": "T"}, headers=owner)).json()["id"]
    made = await client.post(EV, json=create_json(cid), headers=owner)
    assert made.status_code == 201, made.text
    eid = made.json()["id"]
    await add_revisions(client, eid, ["e", "x"], tenant="a")
    rows = await history(client, eid, headers=owner)
    assert [rows[n]["actor_name"] for n in (1, 2, 3)] == ["Olga Owner", "Eve Editor", None]
