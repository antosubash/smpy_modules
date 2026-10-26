"""Per-type permissions in the role editor (upstream #334, ``add_source``).

Three things are asserted: what the source lists (every type, with a label on a
single-tenant host and none on a multi-tenant one), when it is re-read (the
window, a type write, a failed read), and what a grant of
``records.type.<key>`` does — admit a caller ``allowed_roles`` leaves out, and
nothing else, so an install that grants none keeps the access it had.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from permissions.group_labels import localized_groups
from simple_module_core.permissions import PermissionRegistry
from sm_records import constants, type_permissions
from sm_records._permission_sync import PermissionSyncMiddleware
from sm_records.module import RecordsModule
from sm_records.settings import RecordsSettings
from sm_records.tenancy import TenancyMode, tenant_scope

from tests.app_harness import (
    ADMIN,
    ROLE_EDITOR,
    ROLE_EDITOR_TWO,
    ROLE_VIEWER,
    build_app,
    roles,
    seed_type,
)

_INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}


def _module(db_state: Any, mode: TenancyMode = TenancyMode.SINGLE, **settings: Any):
    module = RecordsModule()
    module.settings = RecordsSettings(**settings)
    module.db = db_state
    module.tenancy_mode = mode
    registry = PermissionRegistry()
    module.register_permissions(registry)
    return module, registry


def _records_group(registry: PermissionRegistry):
    """The "records" group exactly as ``GET /api/permissions/`` returns it."""
    [group] = [g for g in localized_groups(registry) if g.name == constants.PERM_GROUP]
    return group


async def test_the_role_editor_lists_every_type_with_its_narrowing(db_state):
    await seed_type(db_state, "company", [], label_plural="Companies")
    await seed_type(db_state, "secret", [], label_plural="Secrets", allowed_roles=["ops", "hr"])
    module, registry = _module(db_state)
    assert _records_group(registry).permissions == [
        constants.PERM_EDIT,
        constants.PERM_MANAGE_TYPES,
        constants.PERM_VIEW,
    ], "nothing before the first read"

    assert await type_permissions.refresh(module, force=True) is True

    group = _records_group(registry)
    assert group.permissions == [
        constants.PERM_EDIT,
        constants.PERM_MANAGE_TYPES,
        "records.type.company",
        "records.type.secret",
        constants.PERM_VIEW,
    ]
    assert group.labels == {
        "records.type.company": "Records: Companies",
        "records.type.secret": "Records: Secrets (restricted to hr, ops)",
    }


@pytest.mark.unbound_tenant
async def test_a_multi_tenant_host_lists_every_tenants_keys_without_labels(db_state):
    for tenant, extra in (("acme", "secret"), ("globex", "invoice")):
        with tenant_scope(tenant):
            await seed_type(db_state, "post", [], label_plural=f"{tenant} posts")
            await seed_type(db_state, extra, [], label_plural=f"{tenant} {extra}s")
    module, registry = _module(db_state, TenancyMode.MULTI)

    await type_permissions.refresh(module, force=True)

    group = _records_group(registry)
    assert [p for p in group.permissions if p.startswith("records.type.")] == [
        "records.type.invoice",
        "records.type.post",
        "records.type.secret",
    ]
    assert group.labels == {}, "one tenant's labels never name another's grants"


async def test_the_window_the_dirty_flag_and_the_invalidation(db_state, monkeypatch):
    await seed_type(db_state, "company", [], label_plural="Companies")
    module, registry = _module(db_state, menu_refresh_seconds=300)
    invalidated: list[str] = []
    real = registry.invalidate_source
    monkeypatch.setattr(registry, "invalidate_source", lambda n: (invalidated.append(n), real(n)))

    assert await type_permissions.refresh(module, force=True) is True
    assert invalidated == [constants.PERM_GROUP]
    await seed_type(db_state, "order", [], label_plural="Orders")
    assert await type_permissions.refresh(module) is False, "inside the window"
    assert "records.type.order" not in registry.all_permissions

    module.mark_menu_dirty()  # what a type write in this process does
    assert await type_permissions.refresh(module) is True
    assert "records.type.order" in registry.all_permissions
    # An unchanged read leaves the registry's caches alone.
    module.mark_menu_dirty()
    assert await type_permissions.refresh(module) is True
    assert invalidated == [constants.PERM_GROUP, constants.PERM_GROUP]


async def test_a_failed_read_keeps_the_previous_list(db_state, caplog):
    await seed_type(db_state, "company", [], label_plural="Companies")
    module, registry = _module(db_state, menu_refresh_seconds=0)
    await type_permissions.refresh(module)

    class _Broken:
        def session_factory(self):
            raise RuntimeError("no such table: records_type")

    module.db = _Broken()
    with caplog.at_level("WARNING"):
        assert await type_permissions.refresh(module) is False
    assert "records.type.company" in registry.all_permissions
    assert "role editor" in caplog.text


async def test_the_middleware_skips_the_records_api_but_not_the_role_editor(db_state, monkeypatch):
    synced: list[str] = []

    async def _fake_refresh(module, *, force=False):
        synced.append("read")
        return True

    monkeypatch.setattr(type_permissions, "refresh", _fake_refresh)
    seen: list[str] = []

    async def _inner(scope, receive, send):
        seen.append(scope.get("path", scope["type"]))

    middleware = PermissionSyncMiddleware(_inner, module=_module(db_state)[0])
    for path in ("/api/records/types", "/static/app.css", "/health/ready"):
        await middleware({"type": "http", "path": path}, _receive, _send)
    assert synced == []
    for path in ("/api/permissions/", "/admin/permissions/roles/x", "/admin/records/"):
        await middleware({"type": "http", "path": path}, _receive, _send)
    assert synced == ["read"] * 3
    assert len(seen) == 6, "skipping the read is not skipping the request"
    await middleware({"type": "websocket"}, _receive, _send)
    assert synced == ["read"] * 3


async def _receive() -> dict:
    return {"type": "http.request"}


async def _send(message: dict) -> None:
    return None


# --- what a grant does --------------------------------------------------------


@pytest_asyncio.fixture
async def granted(tmp_path) -> AsyncIterator[AsyncClient]:
    """``company`` narrowed to editors and shown in the sidebar; the viewer
    role is granted ``records.type.company`` as the role editor would."""
    app, db_state = await build_app(tmp_path, menus=True)
    await seed_type(
        db_state,
        "company",
        [],
        label_plural="Companies",
        show_in_menu=True,
        allowed_roles=[ROLE_EDITOR],
    )
    registry: PermissionRegistry = app.state.sm.permissions
    registry.set_role_overlay(ROLE_VIEWER, ["records.type.company"])
    # What the ``permissions`` module does for admin at startup: every
    # registered key, explicitly — which must not open a narrowed type.
    registry.set_role_overlay(ADMIN, ["records.type.company"])
    await app.state.records_module.on_startup(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        client.app = app  # type: ignore[attr-defined]
        yield client
    await db_state.engine.dispose()


_LIST = "/api/records/types/company/records"


async def test_a_per_type_grant_admits_a_role_allowed_roles_leaves_out(granted):
    assert (await granted.get(_LIST, headers=roles(ROLE_VIEWER))).status_code == 200
    listed = await granted.get("/api/records/types", headers=roles(ROLE_VIEWER))
    assert [t["key"] for t in listed.json()["items"]] == ["company"]


async def test_without_the_grant_the_narrowing_is_unchanged(granted):
    assert (await granted.get(_LIST, headers=roles(ROLE_EDITOR))).status_code == 200
    assert (await granted.get(_LIST, headers=roles(ROLE_EDITOR_TWO))).status_code == 403
    # Admin holds the key explicitly, as after the permissions module's sync,
    # and is still refused: the wildcard grants no per-type access.
    assert (await granted.get(_LIST, headers=roles(ADMIN))).status_code == 403


async def test_the_grant_writes_only_what_records_view_or_edit_already_allow(granted):
    # The viewer is admitted to the type but holds no ``records.edit``.
    created = await granted.post(_LIST, json={"data": {}}, headers=roles(ROLE_VIEWER))
    assert created.status_code == 403


async def test_the_sidebar_follows_the_grant(granted):
    async def labels(*names: str) -> list[str]:
        resp = await granted.get("/admin/records/", headers={**roles(*names), **_INERTIA})
        assert resp.status_code == 200, resp.text
        return [item["label"] for item in resp.json()["props"]["menus"]["adminSidebar"]]

    assert await labels(ROLE_VIEWER) == ["All record types", "Companies"]
    assert await labels(ROLE_EDITOR_TWO) == ["All record types"]
    assert await labels(ADMIN) == ["All record types"]


async def test_a_new_type_reaches_the_role_editor_on_the_next_request(granted):
    created = await granted.post(
        "/api/records/types", json={"key": "invoice", "label": "Invoice"}, headers=roles(ADMIN)
    )
    assert created.status_code == 201
    registry: PermissionRegistry = granted.app.state.sm.permissions  # type: ignore[attr-defined]
    # The window is the default 5 s, so only the write's own mark reads again.
    await granted.get("/admin/records/", headers={**roles(ADMIN), **_INERTIA})
    assert "records.type.invoice" in registry.all_permissions

    deleted = await granted.delete(
        "/api/records/types/invoice?confirm_record_count=0", headers=roles(ADMIN)
    )
    assert deleted.status_code == 204
    await granted.get("/admin/records/", headers={**roles(ADMIN), **_INERTIA})
    assert "records.type.invoice" not in registry.all_permissions
