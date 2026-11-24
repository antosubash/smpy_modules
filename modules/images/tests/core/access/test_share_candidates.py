"""The share dialog's user picker: owner-or-manager only, members only, capped,
and never a listing of the whole directory (#357)."""

from __future__ import annotations

import pytest
from simple_module_core.user_directory import DirectoryUser
from sm_images.models import Collection
from sqlalchemy import select

from tests.support.access import share
from tests.support.isolation import ACME, GLOBEX, as_
from tests.support.stub_auth import as_user, user_uuid

BASE = "/api/images/collections"
WRITER = ("images.view", "images.create")
EVERYONE = {"q": "tester"}
"""Matches every fake display name; three characters or more, as the route needs."""


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


def person(name: str, *, active: bool = True, full_name: str | None = ...) -> DirectoryUser:
    resolved_name = f"{name.title()} Tester" if full_name is ... else full_name
    return DirectoryUser(
        id=user_uuid(name), email=f"{name}@example.com", full_name=resolved_name, is_active=active
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
        {"id": user_uuid("eddie"), "display_name": "Eddie Tester", "email": "e***@example.com"}
    ]
    assert directory.asked[0][0] == "edd"


async def test_is_limited_to_twenty(client):
    client.app.state.user_directory = FakeDirectory([person(f"u{n:02d}") for n in range(40)])
    cid = await make(client, as_user("olga", WRITER))
    r = await client.get(
        f"{BASE}/{cid}/share-candidates", params=EVERYONE, headers=as_user("olga", WRITER)
    )
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
    assert (await client.get(url, params=EVERYONE, headers=mgr)).status_code == 200
    assert (await client.get(url)).status_code == 401


@pytest.mark.parametrize("q", ["", "  ", "a", "ed", " ed  "])
async def test_a_query_under_three_characters_lists_nobody(client, q):
    """Not even the first page of the directory: an empty or one-letter query
    used to walk every account, ``CANDIDATES_MAX`` at a time."""
    directory = FakeDirectory([person("olga"), person("eddie"), person("edna")])
    client.app.state.user_directory = directory
    cid = await make(client, as_user("olga", WRITER))
    r = await client.get(
        f"{BASE}/{cid}/share-candidates", params={"q": q}, headers=as_user("olga", WRITER)
    )
    assert r.status_code == 200
    assert r.json() == []
    assert directory.asked == [], "the directory is not searched at all"


def test_the_picker_has_its_own_per_user_rate():
    from simple_module_core.rate_limit import RateLimitRegistry
    from sm_images.module import ImagesModule
    from sm_images.web.endpoints.api import shares

    rates = RateLimitRegistry()
    ImagesModule().register_rate_limits(rates)
    rule = rates.match("GET", f"{BASE}/abc/share-candidates")
    assert rule is not None and rule.key == "user" and rule.rate == shares.RATE == "60/minute"
    assert rates.match("GET", f"{BASE}/abc") is None
    assert rates.match("GET", f"{BASE}/abc/share-candidates/x") is None


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
    r = await client.get(f"{BASE}/{cid}/share-candidates", params=EVERYONE, headers=owner)
    assert [c["email"] for c in r.json()] == ["a***@example.com"]  # not bob (nobody's), gus (globex)


@pytest.mark.unbound_tenant
async def test_a_multi_tenant_host_with_no_membership_store_offers_nobody(two_tenants):
    client = two_tenants
    client.app.state.user_directory = FakeDirectory([person("olga"), person("amy")])
    owner = as_(ACME, "olga", WRITER)
    cid = await make(client, owner)
    r = await client.get(f"{BASE}/{cid}/share-candidates", params=EVERYONE, headers=owner)
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.unbound_tenant
async def test_a_single_detected_app_with_an_upstream_tenant_still_filters(client):
    """A mis-detected SINGLE host (or mounted child) whose parent resolved a
    tenant must not list other tenants' users."""
    from starlette.middleware.base import BaseHTTPMiddleware

    class Upstream(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if (tenant := request.headers.get("X-Up")) is not None:
                request.state.tenant_id = tenant
            return await call_next(request)

    client.app.add_middleware(Upstream)
    client.app.state.user_directory = FakeDirectory([person("olga"), person("amy"), person("bob")])

    async def tenant_members(db, tenant_id, ids):
        return {i for i in ids if i == user_uuid("amy")}

    client.app.state.tenant_members = tenant_members
    owner = {**as_user("olga", WRITER), "X-Up": ACME}
    cid = await make(client, owner)
    r = await client.get(f"{BASE}/{cid}/share-candidates", params=EVERYONE, headers=owner)
    assert [c["email"] for c in r.json()] == ["a***@example.com"]

    del client.app.state.tenant_members  # no store: fail closed, not "everyone"
    r = await client.get(f"{BASE}/{cid}/share-candidates", params=EVERYONE, headers=owner)
    assert r.json() == []


async def _candidates(client, cid: str, q: str) -> list[dict]:
    r = await client.get(
        f"{BASE}/{cid}/share-candidates", params={"q": q}, headers=as_user("olga", WRITER)
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("q", ["eddie@exa", "@example", "example.com", "ddie@ex", "example"])
async def test_part_of_an_email_finds_nobody(client, q):
    """The directory matches on email substrings; the picker must not become an
    oracle that confirms an address piece by piece."""
    directory = FakeDirectory([person("olga"), person("eddie"), person("amy")])
    client.app.state.user_directory = directory
    cid = await make(client, as_user("olga", WRITER))
    assert await _candidates(client, cid, q) == []
    assert directory.asked[0][0] == q  # the directory was asked; the answer is filtered


@pytest.mark.parametrize("q", ["EDDIE@example.COM", "  eddie@example.com  ", "Eddie@Example.Com"])
async def test_exact_address_in_any_case_returns_the_full_address(client, q):
    client.app.state.user_directory = FakeDirectory([person("olga"), person("eddie")])
    cid = await make(client, as_user("olga", WRITER))
    got = await _candidates(client, cid, q)
    assert [(c["id"], c["email"]) for c in got] == [(user_uuid("eddie"), "eddie@example.com")]


async def test_filter_runs_before_the_limit(client):
    """Email-only hits must not use up the twenty slots a name match needs."""
    people = [person("olga")] + [
        DirectoryUser(
            id=user_uuid(f"u{n:02d}"),
            email=f"zed{n:02d}@example.com",
            full_name=f"Nobody {n}",
            is_active=True,
        )
        for n in range(30)
    ]
    people.append(
        DirectoryUser(
            id=user_uuid("real"),
            email="real@elsewhere.org",
            full_name="Zed Real",
            is_active=True,
        )
    )
    client.app.state.user_directory = FakeDirectory(people)
    cid = await make(client, as_user("olga", WRITER))
    assert [c["id"] for c in await _candidates(client, cid, "zed")] == [user_uuid("real")]


async def test_nameless_user_is_not_labelled_with_the_address(client):
    """With no name the directory's label is the address; the response must not
    carry it in ``display_name`` unless the query is that address."""
    client.app.state.user_directory = FakeDirectory([person("olga"), person("nina", full_name=None)])
    cid = await make(client, as_user("olga", WRITER))
    assert await _candidates(client, cid, "nina") == []
    got = await _candidates(client, cid, "nina@example.com")
    assert got == [
        {
            "id": user_uuid("nina"),
            "display_name": "nina@example.com",
            "email": "nina@example.com",
        }
    ]
    got = await _candidates(client, cid, "NINA@example.com")
    assert got[0]["email"] == "nina@example.com"


async def test_label_containing_an_at_sign_is_masked(client):
    client.app.state.user_directory = FakeDirectory(
        [
            person("olga"),
            DirectoryUser(
                id=user_uuid("ww"),
                email="ww@example.com",
                full_name="Wanda <wanda@corp.example>",
                is_active=True,
            ),
        ]
    )
    cid = await make(client, as_user("olga", WRITER))
    assert await _candidates(client, cid, "wanda") == []
    got = await _candidates(client, cid, "ww@example.com")
    assert got == [
        {"id": user_uuid("ww"), "display_name": "ww@example.com", "email": "ww@example.com"}
    ]
