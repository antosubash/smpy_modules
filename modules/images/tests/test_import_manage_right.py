"""``imports.manage_right.holds_manage``: the worker's re-check of
``images.manage`` against the framework's grant tables."""

from __future__ import annotations

import uuid

import pytest
from sm_images.imports.manage_right import holds_manage
from sm_images.tenancy import DEFAULT_TENANT
from sqlalchemy import delete, select

from tests.pg_support import USING_POSTGRES
from tests.stub_auth import user_uuid

pytestmark = pytest.mark.asyncio
T = DEFAULT_TENANT


async def test_an_unreadable_source_means_cannot_tell(imp):
    # The harness creates no users or tenants tables.
    assert await holds_manage(imp.runtime, T, user_uuid("max")) is None
    assert await holds_manage(imp.runtime, T, "svc:worker") is None


@pytest.mark.skipif(USING_POSTGRES, reason="creates the users/tenants tables ad hoc")
async def test_holds_manage_reads_the_framework_grant_tables(imp):
    from permissions.models import RolePermission, UserPermission
    from tenants.models import Base as TenantsBase
    from users.models._base import Base as UsersBase
    from users.models.role import Role
    from users.models.user import User
    from users.models.user_role import UserRole

    rt, uid = imp.runtime, user_uuid("max")
    async with imp.pipe.db_state.engine.begin() as conn:
        await conn.run_sync(UsersBase.metadata.create_all)
        await conn.run_sync(TenantsBase.metadata.create_all)
    assert await holds_manage(rt, T, uid) is None  # an external principal: no local row
    role = Role(name="curators")
    async with imp.pipe.db_state.session_factory() as s:
        s.add_all([User(id=uuid.UUID(uid), email="max@example.org"), role])
        await s.commit()
        role_id = role.id
    assert await holds_manage(rt, T, uid) is False
    async with imp.pipe.db_state.session_factory() as s:
        s.add(UserRole(user_id=uuid.UUID(uid), role_id=role_id))
        s.add(RolePermission(role_name="curators", permission_key="images.manage"))
        await s.commit()
    assert await holds_manage(rt, T, uid) is True
    async with imp.pipe.db_state.session_factory() as s:
        await s.execute(delete(RolePermission))
        await s.commit()
    assert await holds_manage(rt, T, uid) is False
    async with imp.pipe.db_state.session_factory() as s:
        s.add(UserPermission(user_id=uuid.UUID(uid), permission_key="images.manage"))
        await s.commit()
    assert await holds_manage(rt, T, uid) is True
    async with imp.pipe.db_state.session_factory() as s:
        await s.execute(delete(UserPermission))
        s.add(Role(name="admin"))
        await s.commit()
    async with imp.pipe.db_state.session_factory() as s:
        admin = (await s.execute(select(Role.id).where(Role.name == "admin"))).scalar_one()
        s.add(UserRole(user_id=uuid.UUID(uid), role_id=admin))
        await s.commit()
    assert await holds_manage(rt, T, uid) is True
