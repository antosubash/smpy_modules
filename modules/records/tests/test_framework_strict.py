"""Records under the framework's strict tenancy (framework 0.0.35, #355).

A multi-tenant host builds its ``DatabaseState`` with ``tenant_strict=True``
(``simple_module_hosting.app_builder``): a statement over a
``MultiTenantMixin`` table with no tenant bound raises ``MissingTenantError``
unless it runs inside the framework's own ``all_tenants()`` waiver. The rest of
this suite runs non-strict, as a single-tenant host does, so these tests turn
strict mode on for the paths that read across tenants on purpose: the startup
locale check, ``/health/ready``, ``records tenants`` and the reindex runner.
"""

from __future__ import annotations

import pytest
from simple_module_db import MissingTenantError
from sm_records._cross_tenant import read_all, tenant_counts
from sm_records.models import RecordType
from sm_records.tenancy import tenant_scope
from sqlalchemy import select

from tests.conftest import create_record, create_type

pytestmark = pytest.mark.unbound_tenant


async def _seed(db_state, tenant: str, key: str) -> None:
    with tenant_scope(tenant):
        async with db_state.session_factory() as session:
            rtype = await create_type(session, key, [])
            await create_record(session, rtype, {})
            await session.commit()


@pytest.fixture
async def strict_state(db_state):
    await _seed(db_state, "acme", "post")
    await _seed(db_state, "globex", "page")
    db_state.tenant_strict = True
    return db_state


async def test_strict_mode_is_on_for_an_unbound_plain_read(strict_state):
    """The premise: without the waiver, strict mode refuses the read."""
    async with strict_state.session_factory() as session:
        with pytest.raises(MissingTenantError):
            await session.execute(select(RecordType))


async def test_read_all_sees_every_tenant_under_strict_mode(strict_state):
    async with strict_state.session_factory() as session:
        rows = (await read_all(session, select(RecordType.tenant_id))).scalars().all()
    assert sorted(rows) == ["acme", "globex"]


async def test_read_all_ignores_a_bound_tenant_under_strict_mode(strict_state):
    """``/health/ready`` runs inside ``TenantMiddleware``, which may have bound one."""
    with tenant_scope("acme"):
        async with strict_state.session_factory() as session:
            rows = (await read_all(session, select(RecordType.tenant_id))).scalars().all()
    assert sorted(rows) == ["acme", "globex"]


async def test_tenant_counts_under_strict_mode(strict_state):
    async with strict_state.session_factory() as session:
        counts = await tenant_counts(session)
    assert {t: (c.types, c.records) for t, c in counts.items()} == {
        "acme": (1, 1),
        "globex": (1, 1),
    }
