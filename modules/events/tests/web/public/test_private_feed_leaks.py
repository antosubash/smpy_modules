"""A private feed says "no" in exactly one way, and decides access on every request."""

from __future__ import annotations

import time

import pytest
from sharing.models import ResourceShare
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.tokens import service
from sm_events.models import Calendar
from sqlalchemy import delete, select

from tests.support.access import principal
from tests.support.private_feed import (
    MEMBERS,
    feed_path,
    fingerprint,
    invented,
    private_http,
    seed_world,
)
from tests.support.tokens import NOW

pytestmark = pytest.mark.unbound_tenant
"""Every test binds the tenant it means (the world seeds in one, and the route picks its own)."""

V = "events.view"

CASES = [
    "malformed",
    "unknown",
    "revoked",
    "user_inactive",
    "not_member",
    "roles_unknown",
    "share_removed",
    "view_lost",
    "calendar_trashed",
    "wrong_host_tenant",
    "upstream_tenant_differs",
]


async def _break(http, world, case: str, members) -> dict[str, str]:
    """Make ``case`` true of ``world``'s link; returns the headers its request needs."""
    directory = http.app.state.user_directory
    email, name, _ = directory.users["sv"]
    if case == "revoked":
        async with http.db_state.session_factory() as db:
            with tenant_scope(world.tenant):
                await service.revoke_token(db, principal("sv", V), world.token_id, now=NOW)
                await db.commit()
    elif case == "user_inactive":
        directory.users["sv"] = (email, name, False)
    elif case == "not_member":
        members[world.tenant].discard("sv")
    elif case == "roles_unknown":
        directory.roles["sv"] = None
    elif case == "view_lost":
        directory.roles["sv"] = ("a",)
    elif case == "share_removed":
        async with http.db_state.session_factory() as db:
            with tenant_scope(world.tenant):
                table = ResourceShare.__table__
                await db.execute(
                    delete(table).where(
                        table.c.subject_id == "sv", table.c.tenant_id == world.tenant
                    )
                )
                await db.commit()
    elif case == "calendar_trashed":
        async with http.db_state.session_factory() as db:
            with tenant_scope(world.tenant):
                cal = (
                    await db.execute(select(Calendar).where(Calendar.id == world.cals["P"].id))
                ).scalar_one()
                cal.is_deleted = True
                await db.commit()
    elif case == "upstream_tenant_differs":
        # A single-tenant host where something upstream resolved another tenant: the shortcut
        # that makes everyone a member is off, and with no membership store nobody is.
        return {"X-Test-Tenant": "elsewhere"}
    elif case == "wrong_host_tenant":
        return {"X-Test-Tenant": "elsewhere", "X-Test-Tenant-Source": "subdomain"}
    return {}


@pytest.fixture(params=["single", "multi"])
async def matrix(request, monkeypatch):
    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    multi = request.param == "multi"
    members = {k: set(v) for k, v in MEMBERS.items()}
    async with private_http(multi=multi, members=members) as http:
        tenant = "a" if multi else "default"
        world = await seed_world(http, tenant=tenant)
        yield http, world, members, multi


@pytest.mark.parametrize("case", CASES)
async def test_deny_matrix_byte_identical(matrix, case):
    """Every refusal, however it came about, is one response."""
    http, world, members, multi = matrix
    if case == "not_member" and not multi:
        pytest.skip("a single-tenant host has no memberships")
    if case == "upstream_tenant_differs" and multi:
        pytest.skip("on a multi-tenant host a visitor's tenant proves nothing (see cross-tenant)")
    baseline = fingerprint(await http.get(feed_path(invented("U"))))
    assert baseline[0] == 404 and baseline[1] == constants.PRIVATE_FEED_ERROR_BODY
    headers: dict[str, str] = {}
    if case == "malformed":
        got = await http.get(feed_path("not-a-token"))
    elif case == "unknown":
        got = await http.get(feed_path(invented("V")))
    else:
        headers = await _break(http, world, case, members)
        if multi and "X-Test-Tenant" not in headers:
            headers = {"X-Test-Tenant": world.tenant}  # a visitor session: proves nothing
        assert (await http.get(world.path)).status_code in (404, 200)
        got = await http.get(world.path, headers=headers)
    assert fingerprint(got) == baseline, case
    # ``HEAD`` is the same refusal without a body, and the same for every case.
    head_base = fingerprint(await http.head(feed_path(invented("U"))))
    if case not in ("malformed", "unknown"):
        assert fingerprint(await http.head(world.path, headers=headers)) == head_base, case
    status, body, seen = fingerprint(got)
    assert status == 404
    assert seen["content-type"] == "application/json"
    assert seen["cache-control"] == "no-store"
    assert seen["referrer-policy"] == "no-referrer"
    assert seen["x-robots-tag"] == "noindex"
    for banned in ("vary", "etag", "set-cookie", "location"):
        assert banned not in seen, banned
    assert world.secret.encode() not in body


async def test_every_case_is_actually_a_change(matrix):
    """The matrix is not vacuous: before the change the same request is served."""
    http, world, _members, _multi = matrix
    assert (await http.get(world.path)).status_code == 200


@pytest.mark.parametrize("case", [c for c in CASES if c not in ("malformed", "unknown")])
async def test_deny_respects_floor(matrix, monkeypatch, case):
    http, world, members, multi = matrix
    if case == "not_member" and not multi:
        pytest.skip("a single-tenant host has no memberships")
    if case == "upstream_tenant_differs" and multi:
        pytest.skip("single-tenant only")
    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0.05)
    headers = await _break(http, world, case, members)
    for path in (world.path, feed_path(invented("W")), feed_path("nope")):
        began = time.perf_counter()
        got = await http.get(path, headers=headers)
        assert got.status_code == 404
        assert time.perf_counter() - began >= 0.05, (case, path)


async def test_a_success_is_not_padded(monkeypatch):
    async with private_http() as http:
        world = await seed_world(http)
        monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 5.0)
        began = time.perf_counter()
        assert (await http.get(world.path)).status_code == 200
        assert time.perf_counter() - began < 2.5
