"""A scoped API token never holds more per-type access than its owner's real grants.

The framework caps a token principal at its scopes (``apply_scope_cap``), and
for an admin that *replaces* the wildcard with the scope list — which may name
any registered key, ``records.type.<key>`` included. Per-type grants therefore
come from the owner's genuine grants only: an admin excluded by
``allowed_roles`` is refused through a token exactly as through their session,
while a real grant works through both.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from simple_module_core.permissions import DEFAULT_ROLE_PERMISSIONS, PermissionRegistry
from simple_module_hosting.permissions import apply_scope_cap
from sm_records import constants
from sm_records.services._access import caller_access

from tests.app_harness import ADMIN, ROLE_VIEWER, TEST_SCOPES_HEADER, build_app, roles, seed_type

_LIST = "/api/records/types/payroll/records"
_SCOPES = f"{constants.PERM_VIEW},records.type.payroll"


@pytest_asyncio.fixture
async def payroll(tmp_path) -> AsyncIterator[AsyncClient]:
    """``payroll`` narrowed to ``hr``; the viewer role really holds its key."""
    app, db_state = await build_app(tmp_path)
    await seed_type(db_state, "payroll", [], label_plural="Payroll", allowed_roles=["hr"])
    registry: PermissionRegistry = app.state.sm.permissions
    registry.set_role_overlay(ROLE_VIEWER, ["records.type.payroll"])
    await app.state.records_module.on_startup(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    await db_state.engine.dispose()


def _token(*names: str, scopes: str = _SCOPES) -> dict[str, str]:
    return {**roles(*names), TEST_SCOPES_HEADER: scopes}


async def test_an_excluded_admin_is_refused_by_session_and_by_a_scoped_token(payroll):
    assert (await payroll.get(_LIST, headers=roles(ADMIN))).status_code == 403
    assert (await payroll.get(_LIST, headers=_token(ADMIN))).status_code == 403
    listed = await payroll.get("/api/records/types", headers=_token(ADMIN))
    assert listed.status_code == 200
    assert listed.json()["items"] == []


async def test_a_real_grant_works_by_session_and_by_a_token_scoped_to_it(payroll):
    assert (await payroll.get(_LIST, headers=roles(ROLE_VIEWER))).status_code == 200
    assert (await payroll.get(_LIST, headers=_token(ROLE_VIEWER))).status_code == 200
    # A token that does not carry the key is capped below the grant.
    narrow = _token(ROLE_VIEWER, scopes=constants.PERM_VIEW)
    assert (await payroll.get(_LIST, headers=narrow)).status_code == 403


def test_the_wildcard_owner_gets_no_type_grants_after_the_scope_cap():
    admin_token = SimpleNamespace(roles=[ADMIN], scopes=_SCOPES.split(","))
    held = apply_scope_cap({"*"}, admin_token)
    assert "records.type.payroll" in held, "the framework's cap hands the key over"
    assert caller_access(admin_token, held, DEFAULT_ROLE_PERMISSIONS).granted_types == set()
    # The default map is what applies when no registry is at hand.
    assert caller_access(admin_token, held).granted_types == set()

    viewer = SimpleNamespace(roles=["viewer"], scopes=None)
    access = caller_access(viewer, {"records.type.payroll"}, {"viewer": ["records.view"]})
    assert access.granted_types == {"payroll"}
