"""The share picker, and sharing end to end through the framework's routes."""

from __future__ import annotations

import pytest
from simple_module_core.rate_limit import RateLimitRegistry
from sm_events.module import EventsModule
from sm_events.web.endpoints import shares_api

from tests.support.access import grant
from tests.support.app import Directory, as_user
from tests.support.calendars import make

V, E, P, M = "events.view", "events.edit", "events.publish", "events.manage"
BASE = "/api/events/calendars"
SHARES = "/api/sharing/shares"
RTYPE = "events.calendar"
OWNER = as_user("o", V, E, "sharing.share")
EVERYONE = {"q": "tester"}
"""Matches every fake display name; three characters or more, as the route needs."""

USERS = {
    "o": ("o@example.com", "Olga Tester", True),
    "amy": ("amy@example.com", "Amy Tester", True),
    "bob": ("bob@example.com", "Bob Tester", True),
    "old": ("old@example.com", "Old Tester", False),
}


async def test_owner_gets_candidates(client):
    client.app.state.user_directory = Directory(USERS)
    cid = (await make(client, OWNER))["id"]
    got = await client.get(f"{BASE}/{cid}/share-candidates", params={"q": "amy"}, headers=OWNER)
    assert got.status_code == 200
    assert got.json() == [{"id": "amy", "display_name": "Amy Tester", "email": "a***@example.com"}]
    everyone = await client.get(f"{BASE}/{cid}/share-candidates", params=EVERYONE, headers=OWNER)
    # Not the owner, not the inactive account.
    assert sorted(c["id"] for c in everyone.json()) == ["amy", "bob"]


@pytest.mark.parametrize("count", [20, 21])
async def test_candidates_are_limited_to_twenty(client, count):
    client.app.state.user_directory = Directory(
        {f"u{n:02d}": (f"u{n:02d}@example.com", f"User {n:02d} Tester", True) for n in range(count)}
    )
    cid = (await make(client, OWNER))["id"]
    got = await client.get(f"{BASE}/{cid}/share-candidates", params=EVERYONE, headers=OWNER)
    assert len(got.json()) == 20


@pytest.mark.parametrize("q", ["", "  ", "a", "am", " am  "])
async def test_short_query_is_empty_without_directory_call(client, q):
    directory = Directory(USERS)
    client.app.state.user_directory = directory
    cid = (await make(client, OWNER))["id"]
    got = await client.get(f"{BASE}/{cid}/share-candidates", params={"q": q}, headers=OWNER)
    assert (got.status_code, got.json()) == (200, [])
    assert directory.searches == []


async def test_edit_share_holder_is_403(client):
    client.app.state.user_directory = Directory(USERS)
    cid = (await make(client, OWNER))["id"]
    await grant(client, cid, "se", "edit")
    url = f"{BASE}/{cid}/share-candidates"
    got = await client.get(url, params=EVERYONE, headers=as_user("se", V))
    assert (got.status_code, got.json()["code"]) == (403, "owner_required")
    assert (await client.get(url, params=EVERYONE, headers=as_user("m", V, M))).status_code == 200


async def test_stranger_is_404(client):
    cid = (await make(client, OWNER))["id"]
    got = await client.get(
        f"{BASE}/{cid}/share-candidates", params=EVERYONE, headers=as_user("x", V)
    )
    assert got.status_code == 404
    assert (await client.get(f"{BASE}/{cid}/share-candidates")).status_code == 401


@pytest.mark.unbound_tenant
async def test_other_tenant_members_not_offered(multi_client):
    client = multi_client
    client.app.state.user_directory = Directory(USERS)
    members = {"a": {"amy", "o"}, "b": {"bob"}}

    async def tenant_members(db, tenant_id, ids):
        return {i for i in ids if i in members[tenant_id]}

    client.app.state.tenant_members = tenant_members
    owner = as_user("o", V, E, tenant="a")
    cid = (await client.post(BASE, json={"name": "T"}, headers=owner)).json()["id"]
    got = await client.get(f"{BASE}/{cid}/share-candidates", params=EVERYONE, headers=owner)
    assert [c["id"] for c in got.json()] == ["amy"]  # not bob, who belongs to b
    del client.app.state.tenant_members  # no membership store: fail closed
    got = await client.get(f"{BASE}/{cid}/share-candidates", params=EVERYONE, headers=owner)
    assert got.json() == []


async def test_no_directory_is_503(client):
    cid = (await make(client, OWNER))["id"]
    got = await client.get(f"{BASE}/{cid}/share-candidates", params=EVERYONE, headers=OWNER)
    assert (got.status_code, got.json()["code"]) == (503, "user_directory_unavailable")


def grant_body(cid: str, who: str = "v", role: str = "view") -> dict:
    return {"resource_type": RTYPE, "resource_id": cid, "subject_id": who, "role": role}


async def test_grant_through_sharing_api_single_host(client):
    client.app.state.user_directory = Directory(USERS)
    cid = (await make(client, OWNER))["id"]
    viewer = as_user("amy", V)
    assert (await client.get(f"{BASE}/{cid}", headers=viewer)).status_code == 404
    assert (await client.get(BASE, headers=viewer)).json() == []

    granted = await client.post(SHARES, json=grant_body(cid, "amy"), headers=OWNER)
    assert granted.status_code == 201, granted.text
    seen = await client.get(BASE, headers=viewer)
    assert [c["id"] for c in seen.json()] == [cid]
    assert (await client.get(f"{BASE}/{cid}", headers=viewer)).status_code == 200

    listed = await client.get(
        SHARES, params={"resource_type": RTYPE, "resource_id": cid}, headers=OWNER
    )
    assert [s["subject_id"] for s in listed.json()] == ["amy"]
    revoked = await client.delete(f"{SHARES}/{granted.json()['id']}", headers=OWNER)
    assert revoked.status_code == 204
    assert (await client.get(f"{BASE}/{cid}", headers=viewer)).status_code == 404


async def test_edit_share_holder_cannot_grant(client):
    client.app.state.user_directory = Directory(USERS)
    cid = (await make(client, OWNER))["id"]
    await grant(client, cid, "se", "edit")
    holder = as_user("se", V, "sharing.share")
    got = await client.post(SHARES, json=grant_body(cid, "bob"), headers=holder)
    assert got.status_code in (403, 404), got.text


async def test_share_list_needs_events_view(client):
    """A user who lost ``events.view`` but holds a view share (and
    ``sharing.share``) cannot read the calendar through the shares list."""
    client.app.state.user_directory = Directory(USERS)
    cid = (await make(client, OWNER))["id"]
    await grant(client, cid, "sv", "view")
    query = {"resource_type": RTYPE, "resource_id": cid}
    got = await client.get(SHARES, params=query, headers=as_user("sv", "sharing.share"))
    assert got.status_code == 404, got.text
    # Their owner, too, once events.view is gone.
    got = await client.get(SHARES, params=query, headers=as_user("o", "sharing.share"))
    assert got.status_code == 404, got.text


async def test_stranger_cannot_share_a_calendar_that_is_not_theirs(client):
    client.app.state.user_directory = Directory(USERS)
    cid = (await make(client, OWNER))["id"]
    got = await client.post(
        SHARES, json=grant_body(cid, "bob"), headers=as_user("x", V, "sharing.share")
    )
    assert got.status_code == 404


@pytest.mark.unbound_tenant
async def test_calendar_of_another_tenant_is_not_found_by_the_sharing_router(multi_client):
    client = multi_client
    client.app.state.user_directory = Directory(USERS)
    owner = as_user("o", V, E, "sharing.share", tenant="a")
    cid = (await client.post(BASE, json={"name": "T"}, headers=owner)).json()["id"]
    boss = as_user("m", V, M, "sharing.share", tenant="b")
    got = await client.post(SHARES, json=grant_body(cid, "bob"), headers=boss)
    assert got.status_code == 404
    # A multi-tenant request that resolved no tenant is refused, never defaulted.
    nobody = as_user("o", V, E, "sharing.share")
    got = await client.post(SHARES, json=grant_body(cid, "bob"), headers=nobody)
    assert (got.status_code, got.json()["code"]) == (403, "tenant_required")


def test_rate_limit_rule_registered():
    rates = RateLimitRegistry()
    EventsModule().register_rate_limits(rates)
    rule = rates.match("GET", f"{BASE}/abc/share-candidates")
    assert rule is not None and rule.key == "user"
    assert rule.rate == shares_api.RATE == "60/minute"
    assert rates.match("GET", f"{BASE}/abc") is None
    assert rates.match("GET", f"{BASE}/abc/share-candidates/x") is None


async def _candidates(client, cid: str, q: str) -> list[dict]:
    got = await client.get(f"{BASE}/{cid}/share-candidates", params={"q": q}, headers=OWNER)
    assert got.status_code == 200, got.text
    return got.json()


@pytest.mark.parametrize("q", ["amy@exa", "@example", "example.com", "my@ex", "example"])
async def test_part_of_an_email_finds_nobody(client, q):
    """The directory matches on email substrings; the picker must not become an
    oracle that confirms an address piece by piece."""
    directory = Directory(USERS)
    client.app.state.user_directory = directory
    cid = (await make(client, OWNER))["id"]
    assert await _candidates(client, cid, q) == []
    assert directory.searches == [q]  # the directory was asked; the answer is filtered


@pytest.mark.parametrize("q", ["AMY@example.COM", "  amy@example.com  ", "Amy@Example.Com"])
async def test_exact_address_in_any_case_returns_the_full_address(client, q):
    client.app.state.user_directory = Directory(USERS)
    cid = (await make(client, OWNER))["id"]
    got = await _candidates(client, cid, q)
    assert [(c["id"], c["email"]) for c in got] == [("amy", "amy@example.com")]


async def test_name_match_is_case_insensitive_and_trimmed(client):
    client.app.state.user_directory = Directory(USERS)
    cid = (await make(client, OWNER))["id"]
    got = await _candidates(client, cid, "  BOB tes ")
    assert [c["id"] for c in got] == ["bob"]


async def test_filter_runs_before_the_limit(client):
    """Email-only hits must not use up the twenty slots a name match needs."""
    users = {f"u{n:02d}": (f"zed{n:02d}@example.com", f"Nobody {n}", True) for n in range(30)}
    users["real"] = ("real@elsewhere.org", "Zed Real", True)
    client.app.state.user_directory = Directory(users)
    cid = (await make(client, OWNER))["id"]
    assert [c["id"] for c in await _candidates(client, cid, "zed")] == ["real"]


async def test_nameless_user_is_not_labelled_with_the_address(client):
    """With no name the directory's label is the address; the response must not
    carry it in ``display_name`` unless the query is that address."""
    client.app.state.user_directory = Directory({"nn": ("nina@example.com", None, True)})
    cid = (await make(client, OWNER))["id"]
    got = await _candidates(client, cid, "nina@example.com")
    assert got == [{"id": "nn", "display_name": "nina@example.com", "email": "nina@example.com"}]
    # Matched by the exact address in another case: still the full address, as typed.
    got = await _candidates(client, cid, "NINA@example.com")
    assert got[0]["email"] == "nina@example.com"


async def test_address_label_is_never_matched_by_part_of_it(client):
    client.app.state.user_directory = Directory({"nn": ("nina@example.com", None, True)})
    cid = (await make(client, OWNER))["id"]
    assert await _candidates(client, cid, "nina") == []


async def test_label_containing_an_at_sign_is_masked(client):
    client.app.state.user_directory = Directory(
        {"ww": ("ww@example.com", "Wanda <wanda@corp.example>", True)}
    )
    cid = (await make(client, OWNER))["id"]
    got = await _candidates(client, cid, "wanda")
    assert got == [{"id": "ww", "display_name": "w***@example.com", "email": "w***@example.com"}]


async def test_directory_scan_stops_at_100(client):
    client.app.state.user_directory = Directory(
        {f"u{n}": (f"u{n}@example.com", f"Tester {n}", n >= 99) for n in range(101)}
    )
    cid = (await make(client, OWNER))["id"]
    assert [u["id"] for u in await _candidates(client, cid, "tester")] == ["u99"]


async def test_query_length_at_the_limit(client):
    client.app.state.user_directory = Directory({"u": ("u@x", "x" * 100, True)})
    cid = (await make(client, OWNER))["id"]
    assert [u["id"] for u in await _candidates(client, cid, "x" * 100)] == ["u"]
    got = await client.get(f"{BASE}/{cid}/share-candidates", params={"q": "x" * 101}, headers=OWNER)
    assert got.status_code == 422
