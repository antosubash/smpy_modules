"""A job that runs on an ``images.manage`` right: the worker checks only that
its user still exists, is active and (multi-tenant) is still a member - and
cancels it, failing closed, otherwise (``imports.manage_right``)."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime

import pytest
from sm_images.imports import access
from sm_images.imports.manage_right import manager_active
from sm_images.models import ImportJob
from sm_images.models.enums import JobStatus
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import update

from tests.import_support import b64, feature
from tests.pg_support import USING_POSTGRES
from tests.stub_auth import user_uuid

pytestmark = pytest.mark.asyncio
T = DEFAULT_TENANT
MAX = user_uuid("max")
ad_hoc = pytest.mark.skipif(USING_POSTGRES, reason="creates the users/tenants tables ad hoc")


async def _tables(imp) -> None:
    from tenants.models import Base as TenantsBase
    from users.models._base import Base as UsersBase

    async with imp.pipe.db_state.engine.begin() as conn:
        await conn.run_sync(UsersBase.metadata.create_all)
        await conn.run_sync(TenantsBase.metadata.create_all)


async def _user(imp, **kw) -> None:
    from users.models.user import User

    async with imp.pipe.db_state.session_factory() as s:
        s.add(User(id=uuid.UUID(MAX), email="max@example.org", **kw))
        await s.commit()


async def _managed_job(imp):
    job = await imp.job([feature({"img": b64()})])
    async with imp.pipe.db_state.session_factory() as s:
        stmt = update(ImportJob).where(ImportJob.id == job.id)
        await s.execute(stmt.values(run_as=MAX, access_basis=access.MANAGE))
        await s.commit()
    return job


async def test_no_user_table_fails_closed(imp):
    assert await manager_active(imp.runtime, T, MAX) is False
    assert await manager_active(imp.runtime, T, "svc:worker") is False
    job = await _managed_job(imp)
    assert await imp.run(job) == "cancelled"
    row = await imp.reload(job)
    assert (row.status, row.errors[-1]["code"]) == (JobStatus.CANCELLED, access.ACCESS_REVOKED)


@ad_hoc
async def test_a_deleted_user_is_cancelled(imp):
    await _tables(imp)
    job = await _managed_job(imp)
    assert await imp.run(job) == "cancelled"
    assert await imp.images() == []


@ad_hoc
@pytest.mark.parametrize("state", [{"disabled_at": datetime.now(UTC)}, {"is_active": False}])
async def test_a_disabled_user_is_cancelled(imp, state):
    await _tables(imp)
    await _user(imp, **state)
    job = await _managed_job(imp)
    assert await imp.run(job) == "cancelled"


@ad_hoc
async def test_a_code_mapped_manager_keeps_running(imp):
    # No role or grant row anywhere: the right came from a map_role in code.
    await _tables(imp)
    await _user(imp)
    job = await _managed_job(imp)
    assert await imp.run(job) == "completed"


@ad_hoc
async def test_a_multi_tenant_manager_must_still_be_a_member(imp):
    from tenants.models import Membership, Tenant

    await _tables(imp)
    await _user(imp)
    tenant = Tenant(slug="acme", name="Acme")
    async with imp.pipe.db_state.session_factory() as s:
        s.add(tenant)
        await s.commit()
        acme = tenant.id
    multi = dataclasses.replace(imp.runtime, multi_tenant=lambda: True)
    assert await manager_active(multi, acme, MAX) is False
    async with imp.pipe.db_state.session_factory() as s:
        s.add(Membership(tenant_id=acme, user_id=MAX))
        await s.commit()
    assert await manager_active(multi, acme, MAX) is True
    assert await manager_active(imp.runtime, acme, MAX) is True  # single-tenant host
