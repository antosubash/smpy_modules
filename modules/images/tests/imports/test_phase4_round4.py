"""Phase 4 review fixes, round 4: an unknown tenancy mode is multi-tenant
(fail closed) - only a host known to be single-tenant skips membership."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest
from simple_module_core.tenancy import TenancyMode
from sm_images.imports import access
from sm_images.imports.manage_right import manager_active
from sm_images.models import ImportJob
from sm_images.models.enums import JobStatus
from sm_images.pipeline import runtime as runtime_mod
from sqlalchemy import update

from tests.pg_support import USING_POSTGRES
from tests.support.imports import b64, feature
from tests.support.stub_auth import user_uuid

pytestmark = pytest.mark.asyncio
MAX = user_uuid("max")


def _bare() -> runtime_mod.Runtime:
    return runtime_mod.Runtime(session_factory=None, store=lambda: None, settings=lambda: None)


@pytest.fixture
def configured(monkeypatch):
    """Pin the worker engine's policy as a configured worker would have it."""
    from background_tasks import sync_db

    def pin(strict):
        monkeypatch.setattr(sync_db, "_url_override", "sqlite:///x.db")
        policy = SimpleNamespace(tenant_strict=strict, default_tenant_id=None)
        monkeypatch.setattr(sync_db, "engine_tenancy", lambda: policy)

    return pin


async def test_an_unconfigured_worker_policy_is_multi_tenant(monkeypatch):
    from background_tasks import sync_db

    monkeypatch.setattr(sync_db, "_url_override", None)
    assert _bare().is_multi_tenant() is True


async def test_an_unreadable_worker_policy_is_multi_tenant(configured, monkeypatch):
    from background_tasks import sync_db

    configured(False)

    def broken():
        raise RuntimeError("no policy")

    monkeypatch.setattr(sync_db, "engine_tenancy", broken)
    assert _bare().is_multi_tenant() is True
    monkeypatch.setattr(sync_db, "engine_tenancy", lambda: SimpleNamespace())
    assert _bare().is_multi_tenant() is True  # a policy that does not say


async def test_a_configured_worker_policy_is_taken_at_its_word(configured):
    configured(False)
    assert _bare().is_multi_tenant() is False
    configured(True)
    assert _bare().is_multi_tenant() is True


@pytest.mark.parametrize("mode", [None, "weird", TenancyMode.MULTI])
async def test_a_web_mode_not_clearly_single_is_multi_tenant(mode):
    from sm_images.module import ImagesModule

    app = SimpleNamespace(state=SimpleNamespace(sm=SimpleNamespace(tenancy=mode)))
    try:
        ImagesModule._use_runtime(app, None)
        assert runtime_mod.current_runtime().is_multi_tenant() is True
        app.state.sm.tenancy = TenancyMode.SINGLE
        assert runtime_mod.current_runtime().is_multi_tenant() is False
    finally:
        runtime_mod.use_runtime(None)


async def _users(imp) -> None:
    import uuid

    from tenants.models import Base as TenantsBase
    from users.models._base import Base as UsersBase
    from users.models.user import User

    async with imp.pipe.db_state.engine.begin() as conn:
        await conn.run_sync(UsersBase.metadata.create_all)
        await conn.run_sync(TenantsBase.metadata.create_all)
    async with imp.pipe.db_state.session_factory() as s:
        s.add(User(id=uuid.UUID(MAX), email="max@example.org"))
        await s.commit()


@pytest.mark.skipif(USING_POSTGRES, reason="creates the users/tenants tables ad hoc")
async def test_an_unknown_mode_cancels_a_non_member(imp, monkeypatch):
    from background_tasks import sync_db

    await _users(imp)
    monkeypatch.setattr(sync_db, "_url_override", None)
    unknown = dataclasses.replace(imp.runtime, multi_tenant=None)
    assert await manager_active(unknown, "default", MAX) is False
    imp.pipe.runtime = unknown
    job = await imp.job([feature({"img": b64()})])
    async with imp.pipe.db_state.session_factory() as s:
        stmt = update(ImportJob).where(ImportJob.id == job.id)
        await s.execute(stmt.values(run_as=MAX, access_basis=access.MANAGE))
        await s.commit()
    assert await imp.run(job) == "cancelled"
    row = await imp.reload(job)
    assert (row.status, row.errors[-1]["code"]) == (JobStatus.CANCELLED, access.ACCESS_REVOKED)


@pytest.mark.skipif(USING_POSTGRES, reason="creates the users/tenants tables ad hoc")
async def test_a_known_single_tenant_host_skips_membership(imp):
    await _users(imp)
    single = dataclasses.replace(imp.runtime, multi_tenant=lambda: False)
    assert await manager_active(single, "acme", MAX) is True
