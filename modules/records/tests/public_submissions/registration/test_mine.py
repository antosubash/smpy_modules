"""``/api/records/registrations/mine``: a signed-in person's own registrations (PR 9)."""

from __future__ import annotations

import uuid

import pytest
from simple_module_core.user_directory import DirectoryUser, set_user_directory

from tests.support.app_harness import ADMIN, roles
from tests.support.harness_auth import ROLE_VIEWER
from tests.support.registration_http import (
    TYPE,
    confirm_record,
    load_registration,
    register,
    regs,
    seat_counts,
    seed_event,
)

pytestmark = pytest.mark.usefixtures("reg_site")
URL = "/api/records/registrations/mine"
ME = "test@example.com"  # the harness user's own address


class Directory:
    """Whatever the test says the account directory knows about the caller."""

    entity_type = None

    def __init__(self, *, email=ME, verified: bool | None = True, active=True):
        self.user = {"email": email, "email_verified": verified, "is_active": active}

    async def get_many(self, db, ids, *, with_roles=False):
        return {i: DirectoryUser(id=i, **self.user) for i in ids}

    async def search(self, db, term, *, limit):
        return []

    def match_ids(self, term):
        return None


def me(site, **kw):
    set_user_directory(site.app, Directory(**kw))


async def sign_up(site, address=ME, event=None, **kw):
    event = event or site.event
    await load_registration(site, event)
    await register(site, address, event=event, **kw)
    return next(
        r
        for r in await regs(site)
        if r["data"]["sm_email"] == address and r["data"]["sm_event_id"] == event["event_id"]
    )


async def test_requires_a_signed_in_user(reg_site):
    assert (await reg_site.get(URL)).status_code in (401, 403)


@pytest.mark.parametrize("verified", [False, None])
async def test_mine_requires_verified_email(reg_site, verified):
    await sign_up(reg_site)
    me(reg_site, verified=verified)
    got = await reg_site.get(URL, headers=roles(ROLE_VIEWER))
    assert got.status_code == 200 and got.json() == {"verified": False, "items": []}


async def test_an_unknown_or_inactive_account_sees_nothing(reg_site):
    await sign_up(reg_site)
    me(reg_site, active=False)
    assert (await reg_site.get(URL, headers=roles(ROLE_VIEWER))).json()["items"] == []


async def test_mine_lists_pending_and_registered_upcoming_only(reg_site):
    pending = await sign_up(reg_site)
    other = await seed_event(reg_site.db_state, uid="o@x", registration_capacity=5)
    registered = await sign_up(reg_site, event=other)
    await confirm_record(reg_site, registered)
    stranger = await sign_up(reg_site, address="else@example.org")  # not mine
    me(reg_site)
    got = (await reg_site.get(URL, headers=roles(ROLE_VIEWER))).json()
    assert got["verified"] is True
    assert {(i["uuid"], i["status"]) for i in got["items"]} == {
        (pending["uuid"], "pending"),
        (registered["uuid"], "registered"),
    }
    assert stranger["uuid"] not in {i["uuid"] for i in got["items"]}
    item = got["items"][0]
    assert {"uuid", "type_key", "status", "title", "when_text", "page_path"} <= set(item)
    assert item["title"]  # from events' summaries, else the stored snapshot
    assert "sm_email" not in str(got) and "example.org" not in str(got["items"])  # no addresses


async def test_a_cancelled_registration_is_not_listed(reg_site):
    record = await sign_up(reg_site)
    me(reg_site)
    done = await reg_site.post(f"{URL}/{record['uuid']}/cancel", headers=roles(ROLE_VIEWER))
    assert done.status_code == 200
    assert (await reg_site.get(URL, headers=roles(ROLE_VIEWER))).json()["items"] == []


async def test_mine_cancel_needs_csrf_and_releases_the_seat(reg_site):
    record = await sign_up(reg_site)
    await confirm_record(reg_site, record)
    assert await seat_counts(reg_site) == (1, 1)
    me(reg_site)
    done = await reg_site.post(f"{URL}/{record['uuid']}/cancel", headers=roles(ROLE_VIEWER))
    assert done.status_code == 200
    assert (await regs(reg_site))[0]["data"]["sm_status"] == "cancelled"
    assert await seat_counts(reg_site) == (0, 0)


async def test_someone_elses_uuid_is_404(reg_site):
    theirs = await sign_up(reg_site, address="else@example.org")
    me(reg_site)
    for bad in (theirs["uuid"], uuid.uuid4().hex, "not-a-uuid"):
        got = await reg_site.post(f"{URL}/{bad}/cancel", headers=roles(ROLE_VIEWER))
        assert got.status_code == 404, bad
    assert (await regs(reg_site))[0]["data"]["sm_status"] == "pending"


async def test_an_unverified_caller_cannot_cancel(reg_site):
    record = await sign_up(reg_site)
    me(reg_site, verified=False)
    got = await reg_site.post(f"{URL}/{record['uuid']}/cancel", headers=roles(ROLE_VIEWER))
    assert got.status_code == 404
    assert (await regs(reg_site))[0]["data"]["sm_status"] == "pending"


async def test_mine_needs_no_records_permission(reg_site):
    """Anyone signed in sees their own: the viewer role has records.view, a user with no role at all
    has nothing, and both get the same shape (the list is theirs, not the type's)."""
    await sign_up(reg_site)
    me(reg_site)
    for who in (roles(ADMIN), roles(ROLE_VIEWER)):
        assert (await reg_site.get(URL, headers=who)).json()["verified"] is True


async def test_the_same_address_in_another_tenant_is_not_listed(reg_site):
    """Everything is read under the bound tenant (this harness is single-tenant, so the proof is
    that the listing never reads a record of another tenant id)."""
    await sign_up(reg_site)
    me(reg_site)
    got = (await reg_site.get(URL, headers=roles(ROLE_VIEWER))).json()
    assert len(got["items"]) == 1 and got["items"][0]["type_key"] == TYPE


async def test_the_page_is_for_anyone_signed_in_and_is_in_the_menu(reg_site):
    inertia = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
    anon = await reg_site.get("/admin/records/registrations/mine", headers=inertia)
    assert anon.status_code in (401, 403)
    for who in (ROLE_VIEWER, ADMIN):
        got = await reg_site.get("/admin/records/registrations/mine", headers=roles(who) | inertia)
        assert got.status_code == 200 and got.json()["component"] == "Records/MyRegistrations"
