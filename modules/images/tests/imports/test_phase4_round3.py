"""Phase 4 review fixes, round 3: the manager check reads the host's tenancy
mode (never the tenant id), and a zero-padded Retry-After is a number."""

from __future__ import annotations

import dataclasses
import uuid
from types import SimpleNamespace

import httpx
import pytest
from simple_module_core.tenancy import TenancyMode
from sm_images.imports.manage_right import manager_active
from sm_images.imports.rate_limit import retry_after_seconds
from sm_images.pipeline import runtime as runtime_mod

from tests.support.pg import USING_POSTGRES
from tests.support.stub_auth import user_uuid

pytestmark = pytest.mark.asyncio
MAX = user_uuid("max")


def _mode(imp, multi: bool):
    return dataclasses.replace(imp.runtime, multi_tenant=lambda: multi)


async def _world(imp) -> str:
    """users and tenants tables, an active MAX, and a tenant named ``default``."""
    from tenants.models import Base as TenantsBase
    from tenants.models import Tenant
    from users.models._base import Base as UsersBase
    from users.models.user import User

    async with imp.pipe.db_state.engine.begin() as conn:
        await conn.run_sync(UsersBase.metadata.create_all)
        await conn.run_sync(TenantsBase.metadata.create_all)
    async with imp.pipe.db_state.session_factory() as s:
        s.add(User(id=uuid.UUID(MAX), email="max@example.org"))
        s.add(Tenant(id="default", slug="default-org", name="Default"))
        await s.commit()
    return "default"


@pytest.mark.skipif(USING_POSTGRES, reason="creates the users/tenants tables ad hoc")
async def test_a_multi_tenant_host_checks_membership_even_for_tenant_default(imp):
    from tenants.models import Membership

    tenant = await _world(imp)
    multi = _mode(imp, True)
    assert await manager_active(multi, tenant, MAX) is False
    async with imp.pipe.db_state.session_factory() as s:
        s.add(Membership(tenant_id=tenant, user_id=MAX))
        await s.commit()
    assert await manager_active(multi, tenant, MAX) is True


@pytest.mark.skipif(USING_POSTGRES, reason="creates the users/tenants tables ad hoc")
async def test_a_single_tenant_host_never_checks_membership(imp):
    await _world(imp)
    assert await manager_active(_mode(imp, False), "acme", MAX) is True


async def test_the_runtime_reports_the_hosts_mode():
    rt = runtime_mod.Runtime(session_factory=None, store=lambda: None, settings=lambda: None)
    assert dataclasses.replace(rt, multi_tenant=lambda: True).is_multi_tenant() is True
    assert dataclasses.replace(rt, multi_tenant=lambda: False).is_multi_tenant() is False


async def test_the_web_runtime_follows_the_frameworks_tenancy_mode():
    from sm_images.module import ImagesModule

    app = SimpleNamespace(state=SimpleNamespace(sm=SimpleNamespace(tenancy=TenancyMode.MULTI)))
    try:
        ImagesModule._use_runtime(app, None)
        assert runtime_mod.current_runtime().is_multi_tenant() is True
        app.state.sm.tenancy = TenancyMode.SINGLE
        assert runtime_mod.current_runtime().is_multi_tenant() is False
    finally:
        runtime_mod.use_runtime(None)


async def test_the_worker_runtime_follows_the_engine_policy(monkeypatch):
    from background_tasks import sync_db
    from sm_images.pipeline import worker_runtime

    policy = SimpleNamespace(tenant_strict=True, default_tenant_id=None)
    monkeypatch.setattr(sync_db, "engine_tenancy", lambda: policy)
    monkeypatch.setattr(worker_runtime, "worker_session_factory", lambda: None)
    assert worker_runtime.worker_runtime().is_multi_tenant() is True


async def test_a_zero_padded_retry_after_is_its_number():
    def answer(value: str) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": value})

    assert retry_after_seconds(answer("0000000120")) == 120.0
    assert retry_after_seconds(answer("0000000000000000")) == 0.0
