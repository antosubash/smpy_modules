"""``events.calendar`` as a resource type, and the loader's tenancy rule."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sharing.core.policy import resolve_roles
from simple_module_core.resources import (
    ACTION_EDIT,
    ACTION_VIEW,
    ResourcePolicy,
    ResourceTypeRegistry,
)
from sm_events.core.access import CALENDAR_RESOURCE, POLICY, resource_types
from sm_events.core.errors import TenantRequired
from sm_events.core.tenancy import TenancyMode, tenant_scope
from sm_events.models import Calendar
from sm_events.module import EventsModule

from tests.support.access import seed_calendars


def _app(mode: TenancyMode):
    return SimpleNamespace(state=SimpleNamespace(sm_events=SimpleNamespace(tenancy=mode)))


def _request(mode: TenancyMode, **state):
    return SimpleNamespace(app=_app(mode), state=SimpleNamespace(**state), scope={}, headers={})


def test_registered():
    registry = ResourceTypeRegistry()
    EventsModule().register_resource_types(registry)
    registered = registry.get(CALENDAR_RESOURCE)
    assert CALENDAR_RESOURCE == "events.calendar"
    assert registered is not None
    assert registered.policy is POLICY
    assert isinstance(POLICY, ResourcePolicy)
    # None: sharing's default roles, view and edit.
    assert set(resolve_roles(registered.share_roles)) == {ACTION_VIEW, ACTION_EDIT}


async def _find(db, stmt):
    return (await db.execute(stmt)).scalars().first()


async def test_loader_uses_bound_tenant(db):
    cals = await seed_calendars(db)
    with tenant_scope("default"):
        found = await _find(db, resource_types.calendar_loader()(str(cals["P"].id)))
    assert found is not None and found.id == cals["P"].id


@pytest.mark.unbound_tenant
async def test_loader_single_host_without_binding(db, monkeypatch):
    with tenant_scope("default"):
        mine = (await seed_calendars(db))["P"]
    with tenant_scope("b"):
        theirs = Calendar(slug="other", name="o", owner_id="x")
        db.add(theirs)
        await db.flush()
    monkeypatch.setattr(resource_types, "current_request", lambda: _request(TenancyMode.SINGLE))
    build = resource_types.calendar_loader()
    found = await _find(db, build(str(mine.id)))
    assert found is not None and found.id == mine.id
    assert await _find(db, build(str(theirs.id))) is None


@pytest.mark.unbound_tenant
async def test_loader_multi_without_tenant_raises(monkeypatch):
    monkeypatch.setattr(
        resource_types,
        "current_request",
        lambda: _request(TenancyMode.MULTI, user=SimpleNamespace(id="u")),
    )
    with pytest.raises(TenantRequired):
        resource_types.calendar_loader()("00000000-0000-0000-0000-000000000000")


@pytest.mark.unbound_tenant
def test_loader_no_request_raises(monkeypatch):
    monkeypatch.setattr(resource_types, "current_request", lambda: None)
    with pytest.raises(TenantRequired):
        resource_types.calendar_loader()("00000000-0000-0000-0000-000000000000")


def test_loader_bad_id_is_value_error():
    with pytest.raises(ValueError):
        resource_types.calendar_loader()("not-a-uuid")
