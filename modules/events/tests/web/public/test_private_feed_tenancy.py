"""A private feed binds its link's tenant, and its access is decided per request."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.routing import iter_route_contexts
from sm_events.core import constants
from sm_events.core.tenancy import tenant_scope
from sm_events.feeds.tokens import service
from sm_events.web.endpoints.public import _host_tenant as host_tenant_module
from sm_events.web.endpoints.public import _private_feed, _tenant

from tests.support.access import principal
from tests.support.private_feed import (
    MEMBERS,
    feed_path,
    fingerprint,
    invented,
    mint,
    private_http,
    seed_world,
)
from tests.support.tokens import NOW

pytestmark = pytest.mark.unbound_tenant
V = "events.view"


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


@pytest.mark.parametrize("failing", ["membership", "directory"])
async def test_a_failing_dependency_answers_every_token_alike(monkeypatch, caplog, failing):
    """Revoked, valid and unknown links are the same bytes (GET and HEAD) while the membership
    store or the directory raises: an outage must not tell them apart."""
    from sm_events.core.access import offline

    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    members = {k: set(v) for k, v in MEMBERS.items()}
    async with private_http(multi=True, members=members) as http:
        world = await seed_world(http, tenant="a")
        revoked = await mint(http, world.cals["P"], tenant="a")
        async with http.db_state.session_factory() as db:
            with tenant_scope("a"):
                await service.revoke_token(db, principal("sv", V), revoked.token.id, now=NOW)
                await db.commit()

        async def boom(*_a, **_k):
            raise RuntimeError(f"{failing} down: {world.secret}")

        if failing == "membership":
            monkeypatch.setattr(offline, "tenant_member_ids", boom)
        else:
            http.app.state.user_directory.get_many = boom
        paths = {
            "valid": world.path,
            "revoked": feed_path(revoked.secret),
            "unknown": feed_path(invented("U")),
        }
        with caplog.at_level("DEBUG"):
            for method in ("get", "head"):
                answers = {k: fingerprint(await getattr(http, method)(p)) for k, p in paths.items()}
                assert answers["valid"] == answers["revoked"] == answers["unknown"], method
                assert answers["valid"][0] == 404
        server = [r for r in caplog.records if not r.name.startswith("http")]
        assert any("RuntimeError" in r.getMessage() for r in server)
        for secret in (world.secret, revoked.secret):
            assert all(secret not in r.getMessage() for r in server)


async def test_a_mounted_child_with_no_framework_answer_is_not_single(monkeypatch):
    """The reviewer's case, over HTTP. The app's stored mode is SINGLE and the link's row is
    tenant ``default``, but the app is mounted under a parent (Starlette's ``Mount`` sets
    ``app_root_path``) and the framework has no answer for it, so ``scope_mode`` says MULTI for
    the request: membership is asked. A member is served; once removed, the answer is the same
    bytes as a forged token, never the feed the single-tenant shortcut would have served."""
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sm_events.core.tenancy import _mode

    from tests.support.tokens import install_members

    monkeypatch.setattr(constants, "FEED_DENY_FLOOR_SECONDS", 0)
    async with private_http() as http:
        world = await seed_world(http)
        members = {"default": {"sv"}}
        install_members(http.app, members)
        parent = FastAPI()
        parent.mount("/child", http.app)
        async with AsyncClient(transport=ASGITransport(app=parent), base_url="http://test") as via:
            path = f"/child{world.path}"
            # A normal single-tenant answer first: the framework answers for this app.
            assert (await via.get(path)).status_code == 200
            monkeypatch.setattr(_mode, "_framework_mode", lambda _app: None)
            baseline = fingerprint(await via.get(f"/child{feed_path(invented('U'))}"))
            assert (await via.get(path)).status_code == 200  # a member
            members["default"].discard("sv")  # the owner's membership removed
            for method in ("get", "head"):
                got = fingerprint(await getattr(via, method)(path))
                base = (
                    baseline
                    if method == "get"
                    else fingerprint(await via.head(f"/child{feed_path(invented('U'))}"))
                )
                assert got == base, method
                assert got[0] == 404
