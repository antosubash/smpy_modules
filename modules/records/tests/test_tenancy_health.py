"""The health check and the sidebar sync, in both modes: tenancy design §A.5, §I, §J.

Both run outside any records request. The health check runs from
``/health/ready``, which on a multi-tenant host sits inside ``TenantMiddleware``
and so may be bound to whatever tenant a header named. The sidebar sync runs
before auth and tenant resolution. The first must report every tenant whatever
is bound around it, and name each row it reports as ``tenant/…``. The second
must read only ``default`` on a single-tenant host, and nothing at all on a
multi-tenant one.

Every test opts out of the suite's ``default`` binding and binds for itself.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from simple_module_core.health import HealthStatus
from simple_module_core.menu import MenuRegistry
from sm_records import menu
from sm_records.health import count_orphaned_locales, stale_reindex_check
from sm_records.module import RecordsModule
from sm_records.services._common import utcnow
from sm_records.settings import RecordsSettings
from sm_records.tenancy import TenancyMode, install_guard, tenant_scope

from tests.app_harness import seed_record, seed_type

pytestmark = pytest.mark.unbound_tenant

STALE = {"price": "2020-01-01T00:00:00+00:00"}


@pytest.fixture
async def spread(db_state, field_def):
    """``default`` holds a healthy ``product``. ``acme`` holds a ``product`` with
    a stale marker, one record marked invalid, one in a language the install
    does not publish, and one in the trash."""
    install_guard(db_state.sync_session_class)
    fields = [field_def("price", "number")]
    with tenant_scope("default"):
        home = await seed_type(db_state, "product", fields, show_in_menu=True)
        await seed_record(db_state, home, {"price": 1})
    with tenant_scope("acme"):
        away = await seed_type(
            db_state, "product", fields, reindex_pending=STALE, show_in_menu=True
        )
        await seed_type(db_state, "secret", [], label_plural="Secrets", show_in_menu=True)
        await seed_record(db_state, away, {"price": 2}, invalid_since=utcnow())
        await seed_record(db_state, away, {"price": 3}, locale="xx")
        await seed_record(db_state, away, {"price": 4}, is_deleted=True, deleted_at=utcnow())
    return db_state


def _module(db_state: Any, mode: TenancyMode) -> Any:
    return SimpleNamespace(db=db_state, settings=RecordsSettings(), tenancy_mode=mode)


# --- health -------------------------------------------------------------------


async def test_single_mode_names_every_tenant_and_reports_rows_outside_default(spread):
    # Bound to a third tenant, as a header would bind ``/health/ready``: the
    # check must not narrow to it.
    with tenant_scope("globex"):
        result = await stale_reindex_check(_module(spread, TenancyMode.SINGLE)).check()

    assert result.status is HealthStatus.DEGRADED
    detail = result.detail or ""
    assert "acme/product (price)" in detail
    assert "default/product" not in detail, "default's marker is not stale"
    assert "invalid_records: 1 (acme: 1)" in detail
    assert "tenants_outside_default: {acme: 2 type(s), 3 record(s)}" in detail


async def test_multi_mode_reports_the_same_faults_and_no_foreign_tenants(spread):
    result = await stale_reindex_check(_module(spread, TenancyMode.MULTI)).check()

    detail = result.detail or ""
    assert "acme/product (price)" in detail
    assert "invalid_records: 1 (acme: 1)" in detail
    assert "tenants_outside_default" not in detail, "other tenants are normal here"


async def test_rows_outside_default_are_informational_and_do_not_degrade(db_state):
    """A single-tenant host that keeps another tenant's rows on purpose is
    healthy. The detail still reaches ``/health/ready``, which renders it
    whatever the status."""
    for tenant in ("default", "acme"):
        with tenant_scope(tenant):
            await seed_type(db_state, "product", [])
    result = await stale_reindex_check(_module(db_state, TenancyMode.SINGLE)).check()

    assert result.status is HealthStatus.HEALTHY
    detail = result.detail or ""
    assert detail.startswith("tenants_outside_default: {acme: 1 type(s), 0 record(s)}")


async def test_single_mode_with_only_default_rows_says_nothing_about_tenants(db_state):
    with tenant_scope("default"):
        await seed_type(db_state, "product", [])
    result = await stale_reindex_check(_module(db_state, TenancyMode.SINGLE)).check()
    assert result.status is HealthStatus.HEALTHY


async def test_orphaned_locales_are_counted_per_tenant(spread):
    with tenant_scope("default"):  # the startup read, in a test task that binds one
        counts = await count_orphaned_locales(spread, RecordsSettings())
    assert counts == {"acme/xx": 1}


# --- the sidebar ------------------------------------------------------------------


def _menu_module(db_state: Any, mode: TenancyMode) -> RecordsModule:
    module = RecordsModule()
    module.settings = RecordsSettings()
    module.db = db_state
    module.menu_registry = MenuRegistry()
    module.tenancy_mode = mode
    return module


def _labels(module: RecordsModule) -> list[str]:
    return [item.label for item in module.menu_registry.all_items]


async def test_single_mode_syncs_default_types_only(spread):
    module = _menu_module(spread, TenancyMode.SINGLE)

    assert await menu.refresh(module, force=True) is True
    assert _labels(module) == ["Products"], "acme's Secrets must not reach the sidebar"


async def test_multi_mode_syncs_no_per_type_items_and_reads_nothing(spread):
    module = _menu_module(spread, TenancyMode.SINGLE)
    await menu.refresh(module, force=True)
    assert _labels(module) == ["Products"]

    class _Unreadable:
        def session_factory(self):  # pragma: no cover - must never be called
            raise AssertionError("multi mode reads no sidebar types")

    module.tenancy_mode = TenancyMode.MULTI
    module.db = _Unreadable()
    assert await menu.refresh(module, force=True) is False
    assert _labels(module) == [], "the per-type items this module added are removed"
