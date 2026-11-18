"""A private feed says "no" in exactly one way, and decides access on every request."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.routing import iter_route_contexts
from sharing.models import ResourceShare
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.tokens import service
from sm_events.models import Calendar
from sm_events.web.endpoints.public import _host_tenant as host_tenant_module
from sm_events.web.endpoints.public import _private_feed, _tenant
from sqlalchemy import delete, select

from tests.support.access import principal
from tests.support.private_feed import (
    EVERYONE,
    feed_path,
    invented,
    mint,
    private_http,
    seed_world,
)
from tests.support.tokens import NOW

pytestmark = pytest.mark.unbound_tenant
"""Every test binds the tenant it means (the world seeds in one, and the route picks its own)."""

V = "events.view"
IGNORED = frozenset({"date", "x-correlation-id"})
MEMBERS = {"default": set(EVERYONE), "a": set(EVERYONE), "b": {"sv"}}

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


def fingerprint(response):
    """Status, body and every header but the clock and the request id."""
    headers = {k: v for k, v in response.headers.items() if k not in IGNORED}
    return response.status_code, response.content, headers


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
    status, body, headers = fingerprint(got)
    assert status == 404
    assert headers["content-type"] == "application/json"
    assert headers["cache-control"] == "no-store"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["x-robots-tag"] == "noindex"
    for banned in ("vary", "etag", "set-cookie", "location"):
        assert banned not in headers, banned
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


async def test_cross_tenant_token(monkeypatch):
    """The token's own tenant is bound: the apex serves it, a visitor's tenant is ignored, and
    only the *host's* tenant can refuse it."""
    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    async with private_http(multi=True, members={k: set(v) for k, v in MEMBERS.items()}) as http:
        a = await seed_world(http, tenant="a", tag="-a")
        b = await seed_world(http, tenant="b", tag="-b")
        got = await http.get(b.path)  # the apex: no tenant resolved at all
        assert got.status_code == 200 and b"Published-b" in got.content
        assert b"Published-a" not in got.content
        # A signed-in member of tenant a (or a header) picked a: not the host's doing.
        for headers in (
            {"X-Test-Tenant": "a"},
            {"X-Test-Tenant": "a", "X-Test-Tenant-Source": "session"},
        ):
            got = await http.get(b.path, headers=headers)
            assert got.status_code == 200 and b"Published-b" in got.content, headers
            assert b"Published-a" not in got.content
        # a's own host: b's token is a forgery there.
        host_a = {"X-Test-Tenant": "a", "X-Test-Tenant-Source": "subdomain"}
        refused = await http.get(b.path, headers=host_a)
        assert refused.status_code == 404
        assert refused.content == constants.PRIVATE_FEED_ERROR_BODY
        assert (await http.get(a.path, headers=host_a)).status_code == 200
        assert (await http.get(a.path)).status_code == 200


async def test_feed_is_not_under_public_tenant():
    async with private_http() as http:
        (route,) = (
            c for c in iter_route_contexts(http.app.routes) if c.path == "/events/feed/{token}.ics"
        )
        calls = [d.dependency for d in route.dependencies]

        def walk(dependant):
            for dep in dependant.dependencies:
                calls.append(dep.call)
                walk(dep)

        walk(route.dependant)
        from sm_events.core.tenancy import bind_admin, bind_public

        for forbidden in (_tenant.public_tenant, bind_public, bind_admin):
            assert forbidden not in calls
        assert calls == []  # nothing runs before the handler: it binds the token's tenant itself
        assert route.endpoint is _private_feed.private_feed
        assert route.methods == {"GET", "HEAD"}
        # and it exists on the default language's router only
        assert not [c for c in iter_route_contexts(http.app.routes) if "/de/" in (c.path or "")]


def test_all_tenants_call_sites():
    """The cross-tenant waiver is a place one tenant could read another's rows: a short list."""
    root = Path(_private_feed.__file__).resolve().parents[3]
    found = {
        p.relative_to(root).as_posix()
        for p in root.rglob("*.py")
        if "all_tenants(" in p.read_text() and "core/tenancy/" not in p.as_posix()
    }
    allowed = {
        "content/publish_due.py",
        "core/access/resource_types.py",
        "feeds/importing/janitor.py",
        "feeds/importing/runner.py",
        "feeds/tokens/cleanup.py",
        "feeds/tokens/resolve.py",
    }
    assert "feeds/tokens/resolve.py" in found
    assert found <= allowed, found - allowed


def test_host_tenant_copy():
    from types import SimpleNamespace

    def request(**state):
        return SimpleNamespace(state=SimpleNamespace(**state))

    assert host_tenant_module.host_tenant(request(tenant_source="subdomain", tenant_id="a")) == "a"
    assert host_tenant_module.host_tenant(request(tenant_source="fixed", tenant_id="a")) == "a"
    assert host_tenant_module.host_tenant(request(tenant_source="session", tenant_id="a")) is None
    assert host_tenant_module.host_tenant(request(tenant_source="header", tenant_id="a")) is None
    assert host_tenant_module.host_tenant(request(tenant_id="a")) is None
    assert (
        host_tenant_module.host_tenant(request(tenant_source="subdomain", tenant_id="a b")) is None
    )
    assert host_tenant_module.host_tenant(request(tenant_source="subdomain")) is None


async def test_access_is_decided_per_request_and_not_cached(monkeypatch):
    """The same link serves, stops and serves again with no restart: nothing is remembered."""
    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    async with private_http() as http:
        world = await seed_world(http)
        directory = http.app.state.user_directory
        email, name, _ = directory.users["sv"]
        for _ in range(3):
            assert (await http.get(world.path)).status_code == 200
            directory.users["sv"] = (email, name, False)
            assert (await http.get(world.path)).status_code == 404
            directory.users["sv"] = (email, name, True)
        # Another link of the same user, in the same calendar, behaves the same.
        second = await mint(http, world.cals["P"])
        assert (await http.get(feed_path(second.secret))).status_code == 200


async def test_a_row_of_another_tenant_on_a_single_tenant_host(monkeypatch):
    """The reverse: the link names a tenant this host does not run. The same bytes as a forged
    one, never a feed. (No link could be created for one; the row is inserted directly.)"""
    from sm_events.feeds.tokens.codec import hash_token
    from sm_events.models import Calendar, FeedToken

    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    secret = invented("F")
    async with private_http() as http:
        with tenant_scope("a"):
            async with http.db_state.session_factory() as db:
                cal = Calendar(slug="x", name="X", owner_id="o", visibility="public")
                db.add(cal)
                await db.flush()
                db.add(
                    FeedToken(
                        calendar_id=cal.id,
                        user_id="sv",
                        token_hash=hash_token(secret),
                        label="L",
                        locale="en",
                    )
                )
                await db.commit()
        baseline = fingerprint(await http.get(feed_path(invented("U"))))
        assert fingerprint(await http.get(feed_path(secret))) == baseline
