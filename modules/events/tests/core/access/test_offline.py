"""A token owner's rights, worked out with no session: the feed's only source of access."""

from __future__ import annotations

import pytest
from simple_module_core.resources import ResourcePrincipal
from sm_events.core.access.offline import OfflineUser, offline_principal
from sm_events.core.tenancy import tenant_scope
from starlette.requests import Request

from tests.support.app import Directory, build_app

USERS = {
    "viewer": ("viewer@example.com", "Vera", True),
    "manager": ("manager@example.com", "Manu", True),
    "off": ("off@example.com", "Off", False),
    "idp": ("idp@example.com", "Ida", True),
    "boss": ("boss@example.com", "Bo", True),
    "nobody": ("nobody@example.com", "Nobody", True),
    "other": ("other@example.com", "Other", True),
}
ROLES = {
    "viewer": ("viewer",),
    "manager": ("manager",),
    "off": ("viewer",),
    "idp": None,
    "boss": ("admin",),
    "nobody": (),
    "other": ("viewer",),
}


def _request(app) -> Request:
    return Request({"type": "http", "app": app, "headers": [], "method": "GET", "path": "/"})


@pytest.fixture
async def single():
    app, state = await build_app()
    app.state.user_directory = Directory(USERS, ROLES)
    yield app, state
    await state.engine.dispose()


async def _ask(app, state, user_id, tenant_id="default", **kw):
    async with state.session_factory() as db:
        return await offline_principal(
            app, db, user_id=user_id, tenant_id=tenant_id, request=_request(app), **kw
        )


async def test_role_permissions(single):
    app, state = single
    viewer = await _ask(app, state, "viewer")
    assert isinstance(viewer, ResourcePrincipal)
    assert viewer.user_id == "viewer"
    assert viewer.permissions == frozenset({"events.view"})
    manager = await _ask(app, state, "manager")
    assert manager is not None
    assert manager.permissions == frozenset({"events.view", "events.manage"})


async def test_grant_source_counts(single):
    app, state = single
    seen: list[tuple[str, str]] = []

    async def source(request, user):
        seen.append((user.id, user.tenant_id))
        return {"events.publish"} if user.id == "viewer" else set()

    app.state.sm.permissions.add_grant_source(source)
    viewer = await _ask(app, state, "viewer")
    assert viewer is not None
    assert viewer.permissions == frozenset({"events.view", "events.publish"})
    other = await _ask(app, state, "other")
    assert other is not None
    assert other.permissions == frozenset({"events.view"})
    assert ("viewer", "default") in seen


async def test_a_failing_grant_source_contributes_nothing(single):
    app, state = single

    async def broken(request, user):
        raise RuntimeError("boom")

    app.state.sm.permissions.add_grant_source(broken)
    viewer = await _ask(app, state, "viewer")
    assert viewer is not None and viewer.permissions == frozenset({"events.view"})


async def test_a_user_with_no_roles_holds_nothing(single):
    app, state = single
    nobody = await _ask(app, state, "nobody")
    assert nobody is not None
    assert nobody.permissions == frozenset()
    assert not nobody.has("events.view")


@pytest.mark.parametrize("who", ["missing", "off", "idp"])
async def test_fail_closed_single(single, who):
    """Unknown, deactivated and roles-unknown each resolve to nobody."""
    app, state = single
    assert await _ask(app, state, who) is None


async def test_no_directory_is_nobody():
    app, state = await build_app()  # the harness installs no directory
    try:
        assert await _ask(app, state, "viewer") is None
    finally:
        await state.engine.dispose()


async def test_single_tenant_skips_membership(single):
    app, state = single
    assert not hasattr(app.state, "tenant_members")
    assert await _ask(app, state, "viewer") is not None


async def test_single_tenant_skips_membership_only_when_nothing_upstream_differs(single):
    """The mode is decided per request, as the request paths do: a tenant resolved upstream
    that is not the default means the single-tenant shortcut does not apply, and with no
    membership store to ask, nobody is a member."""
    app, state = single
    async with state.session_factory() as db:
        for upstream, expected in ((None, True), ("default", True), ("a", False)):
            request = _request(app)
            if upstream is not None:
                request.state.tenant_id = upstream
            got = await offline_principal(
                app, db, user_id="viewer", tenant_id="default", request=request
            )
            assert (got is not None) is expected, upstream


async def test_a_mounted_child_with_no_framework_answer_is_not_single(single, monkeypatch):
    """A stored-SINGLE child app the framework has no answer for, mounted under a parent that
    may be multi-tenant: the request resolves ``default`` upstream and the link's tenant is
    ``default``, but ``scope_mode`` says MULTI, so membership is asked, and a removed member
    (or no store at all) is refused."""
    from sm_events.core.tenancy import _mode

    app, state = single
    monkeypatch.setattr(_mode, "_framework_mode", lambda _app: None)
    mounted = Request(
        {
            "type": "http",
            "app": app,
            "headers": [],
            "method": "GET",
            "path": "/",
            "root_path": "/child",
            "app_root_path": "",
        }
    )
    mounted.state.tenant_id = "default"
    members = {"default": {"viewer"}}

    async def tenant_members(db, tenant_id, ids):
        return {i for i in ids if i in members.get(tenant_id, set())}

    async with state.session_factory() as db:

        async def ask():
            return await offline_principal(
                app, db, user_id="viewer", tenant_id="default", request=mounted
            )

        assert await ask() is None  # no membership store: nobody
        app.state.tenant_members = tenant_members
        assert await ask() is not None  # a member
        members["default"].discard("viewer")
        assert await ask() is None  # membership removed: the shortcut must not rescue it
        # The same request on an app the framework does answer for is single again.
        monkeypatch.undo()
        del app.state.tenant_members
        assert await ask() is not None


async def test_no_request_only_a_stored_single_mode_skips_membership(single):
    """A worker has no request: a stored SINGLE mode with the default tenant may skip the
    lookup; any other tenant needs a membership store."""
    app, state = single
    async with state.session_factory() as db:
        assert (
            await offline_principal(app, db, user_id="viewer", tenant_id="default", request=None)
            is not None
        )
        assert (
            await offline_principal(app, db, user_id="viewer", tenant_id="a", request=None) is None
        )


async def test_single_tenant_host_refuses_another_tenant(single):
    """A row for a tenant a single-tenant host does not run is not served."""
    app, state = single
    assert await _ask(app, state, "viewer", tenant_id="b") is None


async def test_wildcard_role(single):
    app, state = single
    boss = await _ask(app, state, "boss")
    assert boss is not None
    assert boss.has("events.manage") and boss.has("events.view")


@pytest.fixture
async def multi():
    app, state = await build_app(multi=True)
    app.state.user_directory = Directory(USERS, ROLES)
    members = {"a": {"viewer", "manager"}, "b": {"other"}}

    async def tenant_members(db, tenant_id, ids):
        return {i for i in ids if i in members.get(tenant_id, set())}

    app.state.tenant_members = tenant_members
    yield app, state, members
    await state.engine.dispose()


@pytest.mark.unbound_tenant
async def test_multi_tenant_needs_membership(multi):
    app, state, _members = multi
    with tenant_scope("a"):
        assert await _ask(app, state, "viewer", tenant_id="a") is not None
        assert await _ask(app, state, "other", tenant_id="a") is None  # a member of b only
    with tenant_scope("b"):
        assert await _ask(app, state, "viewer", tenant_id="b") is None


@pytest.mark.unbound_tenant
async def test_membership_is_read_every_time(multi):
    app, state, members = multi
    with tenant_scope("a"):
        assert await _ask(app, state, "viewer", tenant_id="a") is not None
        members["a"].discard("viewer")
        assert await _ask(app, state, "viewer", tenant_id="a") is None
        members["a"].add("viewer")
        assert await _ask(app, state, "viewer", tenant_id="a") is not None


@pytest.mark.unbound_tenant
async def test_multi_without_a_membership_store_is_nobody(multi):
    app, state, _members = multi
    del app.state.tenant_members
    with tenant_scope("a"):
        assert await _ask(app, state, "viewer", tenant_id="a") is None


@pytest.mark.unbound_tenant
async def test_multi_inactive_member_is_nobody(multi):
    app, state, members = multi
    members["a"].add("off")
    with tenant_scope("a"):
        assert await _ask(app, state, "off", tenant_id="a") is None


def test_offline_user_is_a_plain_principal():
    user = OfflineUser(id="u", roles=("viewer",), tenant_id="default")
    assert user.permissions == () and user.scopes is None and user.required_permission is None
