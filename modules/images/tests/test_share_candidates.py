"""The share dialog's user picker: owner-or-manager only, members only, capped."""

from __future__ import annotations

import pytest
from simple_module_core.user_directory import DirectoryUser
from sm_images.models import Collection
from sqlalchemy import select

from tests.access_support import share
from tests.isolation_support import ACME, GLOBEX, as_
from tests.stub_auth import as_user, user_uuid

BASE = "/api/images/collections"
WRITER = ("images.view", "images.create")


class FakeDirectory:
    entity_type = None

    def __init__(self, users):
        self.users = users
        self.asked: list[tuple[str | None, int]] = []

    async def search(self, db, term, *, limit):
        self.asked.append((term, limit))
        needle = (term or "").lower()
        hits = [
            u
            for u in self.users
            if needle in u.email.lower() or needle in (u.full_name or "").lower()
        ]
        return hits[:limit]

    async def get_many(self, db, ids, *, with_roles=False):
        return {}

    def match_ids(self, term):
        return None


def person(name: str, *, active: bool = True) -> DirectoryUser:
    return DirectoryUser(
        id=user_uuid(name), email=f"{name}@example.com", full_name=name.title(), is_active=active
    )


async def make(client, headers):
    r = await client.post(BASE, json={"name": "Trees"}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_lists_everyone_but_the_owner_and_inactive_on_a_single_tenant_host(client):
    directory = FakeDirectory(
        [person("olga"), person("vic"), person("eddie"), person("old", active=False)]
    )
    client.app.state.user_directory = directory
    cid = await make(client, as_user("olga", WRITER))
    r = await client.get(
        f"{BASE}/{cid}/share-candidates", params={"q": "edd"}, headers=as_user("olga", WRITER)
    )
    assert r.status_code == 200
    assert r.json() == [
        {"id": user_uuid("eddie"), "display_name": "Eddie", "email": "eddie@example.com"}
    ]
    assert directory.asked[0][0] == "edd"


async def test_is_limited_to_twenty(client):
    client.app.state.user_directory = FakeDirectory([person(f"u{n:02d}") for n in range(40)])
    cid = await make(client, as_user("olga", WRITER))
    r = await client.get(f"{BASE}/{cid}/share-candidates", headers=as_user("olga", WRITER))
    assert len(r.json()) == 20


async def test_an_edit_share_gets_403_and_a_stranger_404(client):
    client.app.state.user_directory = FakeDirectory([person("vic")])
    cid = await make(client, as_user("olga", WRITER))
    async with client.db_state.session_factory() as s:
        coll = (await s.execute(select(Collection))).scalars().one()
        s.add(share(coll, "eddie", "edit"))
        await s.commit()
    url = f"{BASE}/{cid}/share-candidates"
    assert (await client.get(url, headers=as_user("eddie", WRITER))).status_code == 403
    assert (await client.get(url, headers=as_user("sam", WRITER))).status_code == 404
    mgr = as_user("max", (*WRITER, "images.manage"))
    assert (await client.get(url, headers=mgr)).status_code == 200
    assert (await client.get(url)).status_code == 401


async def test_no_user_directory_is_503_with_a_code(client):
    cid = await make(client, as_user("olga", WRITER))
    r = await client.get(f"{BASE}/{cid}/share-candidates", headers=as_user("olga", WRITER))
    assert r.status_code == 503
    assert r.json()["code"] == "user_directory_unavailable"


@pytest.mark.unbound_tenant
async def test_a_multi_tenant_host_offers_only_members_of_the_bound_tenant(two_tenants):
    client = two_tenants
    people = [person("olga"), person("amy"), person("bob"), person("gus")]
    client.app.state.user_directory = FakeDirectory(people)
    members = {ACME: {user_uuid("amy"), user_uuid("olga")}, GLOBEX: {user_uuid("gus")}}

    async def tenant_members(db, tenant_id, ids):
        return {i for i in ids if i in members[tenant_id]}

    client.app.state.tenant_members = tenant_members
    owner = as_(ACME, "olga", WRITER)
    cid = await make(client, owner)
    r = await client.get(f"{BASE}/{cid}/share-candidates", headers=owner)
    assert [c["email"] for c in r.json()] == ["amy@example.com"]  # not bob (nobody's), gus (globex)


@pytest.mark.unbound_tenant
async def test_a_multi_tenant_host_with_no_membership_store_offers_nobody(two_tenants):
    client = two_tenants
    client.app.state.user_directory = FakeDirectory([person("olga"), person("amy")])
    owner = as_(ACME, "olga", WRITER)
    cid = await make(client, owner)
    r = await client.get(f"{BASE}/{cid}/share-candidates", headers=owner)
    assert r.status_code == 200
    assert r.json() == []
